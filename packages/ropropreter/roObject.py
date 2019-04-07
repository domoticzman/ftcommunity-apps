#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
from bs4 import BeautifulSoup
import time

__author__     = "Leon Schnieber"
__copyright__  = "Copyright 2018-2019"
__credits__    = "fischertechnik GmbH"
__maintainer__ = "Leon Schnieber"
__email__      = "olaginos-buero@outlook.de"
__status__     = "Developement"


class RoboProObject(object):
    """
    This object can be either generated by an XML-String or via the attributes
    itself. Therefor objectXmlSoup has to be None so the attributes can be set
    manually. This feature is mainly used for Pseudo-Objects used on converging
    wires.
    """


    normal = 0
    reverse = 1

    def __init__(self, subroutineToolbox, objectXmlSoup=None):
        self._objectRaw = objectXmlSoup
        self._subrtTools = subroutineToolbox
        self._data = None  # Empty variable e.g. to use for constants etc.
        self._type = None  # Category of the block, e.g. ftProProcessStart
        self._id = ""  # Internal ID given in the XML-Structure
        self._pins = []  # list of data- and flow-connection-pins
        if self._objectRaw is not None:
            self.parse()

    def __repr__(self):
        return "RoObj_" + self._id + "_" + self._type

    def parse(self):
        '''
        Extract all necessary informations about this Diagram-Block out of the
        given XML-Structure and store it in different Variables.
        '''
        self._type = self._objectRaw.attrs["classname"]
        try:
            self._id = self._objectRaw.attrs["id"]
        except KeyError:
            self._id = ""
        pinList = self._objectRaw.find_all("o", attrs=
            {"classname": "ftProObjectPin"})
        for pin in pinList:
            pinData = {
                "id": pin.attrs["id"],
                "pinid": pin.attrs["pinid"],
                "name": pin.attrs["name"],
                "pinclass": pin.attrs["pinclass"]
            }
            self._pins.append(pinData)

    def getPinIdByClass(self, pinclass):
        '''
        Fetch and return all connection pins of a given type
        '''
        return self.getPinIdByAttr("pinclass", pinclass)

    def getPinIdByAttr(self, attr, value):
        '''
        Fetch and return all connection pins of a given type and value
        '''
        list = []
        for pin in self._pins:
            if value in pin[attr]:
                list.append(pin["id"])
        return list

    def run(self, inputID=None, arguments={}, mode=0):
        '''
        This function is called by the Subroutine-Object. Depending on its object
        type it takes additional input arguments (e.g. Input-Sensors or variables)
        and returns the next coutputID (e.g. important for an if-else-Block).
        Additionally it may return additional Arguments, e.g. for Motor-Outputs.
        Depending on the mode-argument the single elements change their propagation-
        behaviour. In normal Mode, they act forward, so they only find their "next"
        object in the chain. In reverse-Mode they backpropagate to get the values
        they work with. Not all blocks have to handle with that but there are some
        where this is quite helpful.
        '''
        outputID = None
        # print(self)  # debug output prints every object it processes
        if self._type == "ftProProcessStart": # program start block
            outputID = self.getPinIdByClass("flowobjectoutput")[0]
        elif self._type == "ftProFlowIf":  # if block
            styleNo = int(self._objectRaw.attrs["style"])
            # style-types:
            # 1  = 8.6-Verzweigung mit Dateneingang
            # 2  = 8.1-Verzweigung Digital/Analog
            if styleNo == 1: # Verzweigung mit Dateneingang
                # Get Pin-IDs for the Yes-Outputs and No-Outputs
                outYes = self.getPinIdByAttr("name", "J")[0]
                outNo = self.getPinIdByAttr("name", "N")[0]
                # start backpropagating process to get a value for the comparsion
                pinIDin = self.getPinIdByClass("dataobjectinput")[0]
                # get the backpropagated value and return IDs depending on the value
                val = self.calculateDataValue(pinIDin)["value"]
                if val == 1 or val == True or val > 0:
                    outputID = outYes
                else:
                    outputID = outNo
            elif styleNo == 2:  # Verzweigung Digital
                IFNo, IFPortNo, IFPortMode = self.readInputMeta()
                val = self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode)
                try:
                    outYes = self.getPinIdByAttr("name", "J")[0]
                    outNo = self.getPinIdByAttr("name", "N")[0]
                except IndexError:
                    outYes = self.getPinIdByAttr("name", "1")[0]
                    outNo = self.getPinIdByAttr("name", "0")[0]
                if "operation" in self._objectRaw.attrs:
                    oper = int(self._objectRaw.attrs["operation"])
                    triggerVal = int(self._objectRaw.attrs["value"])
                    if (oper == 0 and val > triggerVal) \
                        or (oper == 1 and val >= triggerVal) \
                        or (oper == 2 and val == triggerVal) \
                        or (oper == 3 and val <= triggerVal) \
                        or (oper == 4 and val < triggerVal) \
                        or (oper == 5 and (val < triggerVal or val > triggerVal)):
                        outputID = outYes
                    else:
                        outputID = outNo
                else:
                    if val == 1 or val == True or val > 0:
                        outputID = outYes
                    else:
                        outputID = outNo
        elif self._type == "ftProDataIn": # sensor/data-in block
            # fetch type dependent settings
            IFNo, IFPortNo, IFPortMode = self.readInputMeta()
            arguments["value"] = self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode)
        elif self._type == "dataHelper": # merging Cable nodes
            if mode == self.normal:
                try:
                    outputID = self.getPinIdByAttr("name", "flowobjectoutput")[0]
                except IndexError:
                    outputID = self.getPinIdByAttr("name", "dataobjectoutput")[0]
                # outputID = self._subrtTools._followWire(outputID)
            elif mode == self.reverse:
                pass
        elif self._type == "ftProDataMssg":  # motor and output commands
            if mode == self.normal:
                pinIDIn = self.getPinIdByClass("dataobjectinput")
                if len(pinIDIn) >= 1:
                    # backpropagate data from the connecting wires
                    value = int(self.calculateDataValue(pinIDIn[0])["value"])
                else:
                    # get the value from the metadata
                    value = int(self._objectRaw.attrs["value"])
                comType = self._objectRaw.attrs["command"]
                # List of availiable types
                # "="    = Set      (= n)
                # "+"    = Incr     (= n+1)
                # "-"    = Decr     (= n-1)
                # "cw"   = CW Mot   (v=n)
                # "ccw"  = CCW Mot  (v=n)
                # "Stop" = Stop Mot (v=0)
                # "On"   = On IO    (v=n)
                # "Off"  = Off IO   (v=0)
                # "Ap…d" = Append n to list
                # "Re…e" = Remove nth list-element
                # "Swap" = Swap nth element with first element in list

                # "branch out" of subroutine-run-thread and try to reach all connected wires with the data
                # "frontpropagate" all paths and call their "run"-Functions
                arguments = {
                "commandType": comType,
                "value": value
                }
                # print(arguments)
                tOutputID = self.getPinIdByClass("dataobjectoutput")[0]
                self.calculateFollowers(tOutputID, arguments)
                outputID = self.getPinIdByClass("flowobjectoutput")[0]
            elif mode == self.reverse:
                pass  # do nothing, the object isn't called actively
        elif self._type == "ftProDataOutDual":  # dual-motor-commands
            # if this object is used as an Level 1 Object, it has to fetch its arguments by itself
            if "classic" in self._objectRaw.attrs:
                arguments["commandType"] = self._objectRaw.attrs["command"]
                if self._objectRaw.attrs["value"] == "-32768":
                    arguments["value"] = 0
                else:
                    arguments["value"] = int(self._objectRaw.attrs["value"]) * 64 # directly multiply because of classic-elements not supporting 512-step-mode
                # in classic mode elements have to find their output for the next element
                outputID = self.getPinIdByClass("flowobjectoutput")[0]
            # get Details
            IFaceNumber = self._objectRaw.attrs["module"]
            IFacePortNo = int(self._objectRaw.attrs["output"])
            try:
                IFacePortRes = int(self._objectRaw.attrs["resolution"])
                if IFacePortRes == 0:  # if resolution is 0-8 convert it to 512-System
                    arguments["value"] = int(arguments["value"]) * 64
            except KeyError:
                pass
            # do something with the IO
            # print(IFacePortNo, arguments)
            self._subrtTools._io.setOutputValue(IFaceNumber, IFacePortNo, arguments)
        elif self._type == "ftProDataOutDualEx":  # encodermotor
            IFaceNumber = self._objectRaw.attrs["module"]
            dir1 = self._objectRaw.attrs["direction1"]
            dir2 = self._objectRaw.attrs["direction2"]
            comType1 = "cw" if dir1 == "0" else "ccw"
            comType2 = "cw" if dir2 == "0" else "ccw"
            distance = int(self._objectRaw.attrs["distance"])
            value = int(self._objectRaw.attrs["speed"]) * 64
            out1 = int(self._objectRaw.attrs["output1"])
            out2 = int(self._objectRaw.attrs["output2"]) -1  # minus one because of the "none"-option
            # Values for out1 and out2
            # 0  = M1
            # 1  = M2
            # …
            # 3  = M4
            args1 = {
                "value": value,
                "commandType": comType1
            }
            stop = {
                "value": 0,
                "commandType": "cw"
            }
            if self._objectRaw.attrs["action"] == "0":  # distance
                args1["distance"] = distance
                args1["sleep"] = True
                self._subrtTools._io.setOutputValue(IFaceNumber, out1, args1)
            elif self._objectRaw.attrs["action"] == "1":  # synchron
                args2 = {
                    "value": value,
                    "commandType": comType2,
                    "syncTo": out1
                }
                args1["syncTo"] = out2
                self._subrtTools._io.setOutputValue(IFaceNumber, out1, args1)
                self._subrtTools._io.setOutputValue(IFaceNumber, out2, args2)
            elif self._objectRaw.attrs["action"] == "2":  # synchron distance
                args2 = {
                    "value": value,
                    "distance": distance,
                    "commandType": comType2,
                    "syncTo": out1,
                }
                args1["distance"] = distance
                args1["syncTo"] = out2

                args2["sleep"] = True
                self._subrtTools._io.setOutputValue(IFaceNumber, out1, args1)
                if out2 is not -1:
                    self._subrtTools._io.setOutputValue(IFaceNumber, out2, args2)
            elif self._objectRaw.attrs["action"] == "3":  # stopp
                args = {
                    "value": 0,
                    "commandType": "cw"
                }
                self._subrtTools._io.setOutputValue(IFaceNumber, out1, args)
                if out2 is not -1:
                    self._subrtTools._io.setOutputValue(IFaceNumber, out2, args)
            outputID = self.getPinIdByClass("flowobjectoutput")[0]
        elif self._type == "ftProDataOutSngl":  # single output (lamp)
            # if this object is used as an Level 1 Object, it has to fetch its arguments by itself
            if "classic" in self._objectRaw.attrs:
                IFaceNumber = self._objectRaw.attrs["module"]
                IFacePortNo = int(self._objectRaw.attrs["output"]) + 4
                IFacePortValue = int(self._objectRaw.attrs["value"])
                IFacePortSettings = {
                    "value": IFacePortValue
                }
                self._subrtTools._io.setOutputValue(IFaceNumber, IFacePortNo, IFacePortSettings)
                outputID = self.getPinIdByClass("flowobjectoutput")[0]
            else:  # if it is used as an orange-dataflow-object it gets its value via the dataline
                # print(self._objectRaw)
                IFaceNumber = self._objectRaw.attrs["module"]
                IFacePortNo = int(self._objectRaw.attrs["output"]) + 4
                IFaceResolution = int(self._objectRaw.attrs["resolution"])
                IFacePortValue = int(arguments["value"]) if IFaceResolution == 0 else int(arguments["value"]) * 64
                IFacePortValue = IFacePortValue if IFacePortValue >= 0 else 0
                IFacePortSettings = {
                    "value": IFacePortValue
                }
                self._subrtTools._io.setOutputValue(IFaceNumber, IFacePortNo, IFacePortSettings)
                outputID = None
        elif self._type == "ftProFlowWaitChange" or self._type == "ftProFlowWaitCount": # wait for pulse change
            if "classic" in self._objectRaw.attrs:
                self._data = 0
                if "count" in self._objectRaw.attrs:
                    limit = int(self._objectRaw.attrs["count"])
                else:
                    limit = 1
                while self._data < limit:
                    self._data += 1
                    IFNo, IFPortNo, IFPortMode = self.readInputMeta()
                    value = self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode)
                    if "level" in self._objectRaw.attrs:
                        if "up" in self._objectRaw.attrs:  # "0"
                            while value is not 1:
                                time.sleep(0.01)
                                value = self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode)
                        elif "down" in self._objectRaw.attrs:  # "1"
                            while value is not 0:
                                time.sleep(0.01)
                                value = self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode)
                    else:
                        if "up" in self._objectRaw.attrs:
                            if "down" in self._objectRaw.attrs:  # up>down or down>up
                                c = value
                                while c == self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode):
                                    time.sleep(0.01)
                            else: # down>up
                                while self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode) != 0:
                                    time.sleep(0.01)
                                while self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode) != 1:
                                    time.sleep(0.01)
                        elif "down" in self._objectRaw.attrs: # up>down
                            while self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode) != 1:
                                time.sleep(0.01)
                            while self._subrtTools._io.getSensorValue(IFNo, IFPortNo, IFPortMode) != 0:
                                time.sleep(0.01)
                outputID = self.getPinIdByClass("flowobjectoutput")[0]
            else:
                print("ERROR on", self._type, "is not from type classic")
        elif self._type == "ftProFlowCountLoop":  # single loop
            cycleCount = int(self._objectRaw.attrs["count"])
            # Get Input-Pin-Data
            lastPin = self._subrtTools._lastPin
            try:
                pinName = self._findPin(lastPin)["name"]
            except IndexError:
                pinName = ""
            # Check conditions
            if pinName == "=1":
                self._data = 1
                outputID = self.getPinIdByAttr("name", "N")[0]
            elif pinName == "+1":
                self._data += 1
                if self._data > cycleCount:
                    outputID = self.getPinIdByAttr("name", "J")[0]
                else:
                    outputID = self.getPinIdByAttr("name", "N")[0]
            else:
                print("ERROR", pinName)
        elif self._type == "ftProFlowSound":  # play sound stuff
            if "sounindex" in self._objectRaw.attrs:
                index = self._objectRaw.attrs["sounindex"]
                wait = bool(self._objectRaw.attrs["wait"])
                repeat = self._objectRaw.attrs["repeatcount"]
                IFaceNumber = "IF1"  # roboPro does not deliver this information
                self._subrtTools._io.setSound(IFaceNumber, index, wait, repeat)
            else:
                print("ERROR: Sound element isn't formatted well")
            outputID = self.getPinIdByClass("flowobjectoutput")[0]
            pass
        elif self._type == "ftProDataConst":  # constant-variables
            arguments["value"] = float(self._objectRaw.attrs["value"])
        elif self._type == "ftProDataVariable":
            if self._data is None:
                self._data = {}
            if "scope" not in self._data:
                self._data["scope"] = int(self._objectRaw.attrs["scope"])
            name = self._objectRaw.attrs["name"]
            if mode == self.normal: # if variable isn't initialized yet
                # print("normal", self._data["scope"])
                if self._data["scope"] == 2:  # scope = object
                    if "value" in arguments and "commandType" in arguments:
                        val = self._data["value"]
                        if arguments["commandType"] == "=":
                            valueT = float(arguments["value"])
                        elif arguments["commandType"] == "+":
                            valueT = float(val) + float(arguments["value"])
                        elif arguments["commandType"] == "-":
                            valueT = float(val) - float(arguments["value"])
                        else:
                            print("ERROR", "command cannot be applied on variables")
                    else:
                        valueT = float(self._objectRaw.attrs["init"])
                    self._data["value"] = valueT
                elif self._data["scope"] == 1:  # scope = global
                    if self._subrtTools._roProg._data is None:
                        self._subrtTools._roProg._data = {}
                    if "variable" not in self._subrtTools._roProg._data:
                        self._subrtTools._roProg._data["variable"] = {}
                    if "value" in arguments and "commandType" in arguments:
                        if name in self._subrtTools._roProg._data["variable"]:
                            val = self._subrtTools._roProg._data["variable"][name]
                        else:
                            val = float(self._objectRaw.attrs["init"])
                        if arguments["commandType"] == "=":
                            valueT = float(arguments["value"])
                        elif arguments["commandType"] == "+":
                            valueT = float(val) + float(arguments["value"])
                        elif arguments["commandType"] == "-":
                            valueT = float(val) - float(arguments["value"])
                        else:
                            print("ERROR", "command cannot be applied on variables")
                    else:
                        valueT = float(self._objectRaw.attrs["init"])
                    self._subrtTools._roProg._data["variable"][name] = valueT
                elif self._data["scope"] == 0:  # scope = local, in subprogram
                    if self._subrtTools._data is None:
                        self._subrtTools._data = {}
                    if "variable" not in self._subrtTools._data:
                        self._subrtTools._data["variable"] = {}
                    if "value" in arguments and "commandType" in arguments:
                        if name in self._subrtTools._data["variable"]:
                            val = self._subrtTools._data["variable"][name]
                        else:
                            val = float(self._objectRaw.attrs["init"])
                        if arguments["commandType"] == "=":
                            valueT = float(arguments["value"])
                        elif arguments["commandType"] == "+":
                            valueT = float(val) + float(arguments["value"])
                        elif arguments["commandType"] == "-":
                            valueT = float(val) - float(arguments["value"])
                        else:
                            print("ERROR", "command cannot be applied on variables")
                    self._subrtTools._data["variable"][name] = valueT
            if mode == self.reverse:  # set variable to new value
                arguments["value"] = float(self._objectRaw.attrs["init"])
                if self._data["scope"] == 2:  # localobj
                    if name in self._data["variable"]:
                        arguments["value"] = float(self._data["value"])
                elif self._data["scope"] == 1:  # global
                    if name in self._subrtTools._roProg._data["variable"]:
                        arguments["value"] = float(self._subrtTools._roProg._data["variable"][name])
                elif self._data["scope"] == 0:  # local subprogram
                    if name in self._subrtTools._data["variable"]:
                        arguments["value"] = self._subrtTools._data["variable"][name]
                # print("ARGS", arguments)
        elif self._type == "ftProFlowDelay":  # normal waiting-function
            value = float(self._objectRaw.attrs["value"]) \
                    * 10**int(self._objectRaw["scale"]) * 0.001
            time.sleep(value)
            outputID = self.getPinIdByClass("flowobjectoutput")[0]
        ### START SUBROUTINE-OBJECT-TYPES
        elif self._type == "ftProSubroutineRef":  # subroutine-block
            """
            get subroutine-Name and find entry-pin-id
            """
            subrtName = self._objectRaw.attrs["name"]
            subroutines = self._subrtTools._subrts
            lastPin = self._subrtTools._lastPin
            if subrtName in subroutines:
                subrt = subroutines[subrtName]
                pinData = self._findPin(lastPin)
                inputPinUID = pinData["pinid"]
                endObj = subrt._findSubrtInputObject(inputPinUID)[1]
                refSubrt = self._subrtTools._name
                refObj = self
                subrtOutputObj = subrt.run(endObj, refSubrt, refObj)
                subrtOutputUID = subrtOutputObj._objectRaw.attrs["uniqueID"]
                for pin in self._pins:
                    if pin["pinid"] == subrtOutputUID:
                        outputID = pin["id"]
            else:
                print("The subroutine " + str(subrtName) + " cannot be found in this file.")
        elif self._type == "ftProSubroutineFlowIn":  # subroutine-flow-input-block
            outputID = self.getPinIdByClass("flowobjectoutput")[0]
        elif self._type == "ftProSubroutineFlowOut":  # subroutine-flow output block
            # should not be needed because of exception in the subrt-run-function
            outputID = self._id
        elif self._type == "ftProSubroutineDataIn":
            outerObject = self._subrtTools._subrtReference[1]
            innerUID = self._objectRaw.attrs["uniqueID"]
            outerPinID = outerObject.getPinIdByAttr("pinid", innerUID)[0]
            outerPin = self._findPin(outerPinID)
            arguments = outerObject.calculateDataValue(outerPinID)
        elif self._type == "ftProSubroutineDataOut":
            # use information in self._subrtTools._subrtReference to start
            outerObject = self._subrtTools._subrtReference[1]
            innerUID = self._objectRaw.attrs["uniqueID"]
            outerPinID = outerObject.getPinIdByAttr("pinid", innerUID)[0]
            outerObject.calculateFollowers(outerPinID, arguments)
            pass
        ### STOP SUBROUTINE-OBJECT-TYPES
        elif self._type == "ftProProcessStop":
            outputID = None
            arguments = None
        else:
            print("ERROR:", self._type, "isn't yet implemented.")
        return outputID, arguments

    def calculateDataValue(self, pinIDin):
        '''
        This function is especially important for objects who use data-flow-wires
        to get their information. It tries to follow the orange connections in
        reverse direction, back to their origins. (in reverse-direction-mode)
        '''
        dataInBack = self._subrtTools._followWireReverse(pinIDin)
        pins, objectBack = self._subrtTools._findObject(dataInBack)
        outputID, arguments = objectBack.run(mode=self.reverse)
        return arguments

    def calculateFollowers(self, pinIDout, arguments):
        '''
        This function follows the orange wires to all open ends and tries to "run"
        them in normal-direction-mode so motors can be set etc.
        '''
        dataInNext = self._subrtTools._followWireList(pinIDout)
        for wire in dataInNext:
            objPinList, obj = self._subrtTools._findObject(wire)
            outputID, arguments = obj.run(arguments=arguments)
            while outputID is not None:
                folWir = self._subrtTools._followWire(outputID)
                pinList, object = self._subrtTools._findObject(folWir)
                if object is not None:
                    object.run(arguments=arguments)
                    outputID = object._id
                else:
                    break
            # print("RUN", obj, obj.run(arguments=arguments))

    def readInputMeta(self):
        """
        This helper function is mainly used in the IO-Specific blocks where the
        same three parameters are used over and over again.
        """
        IFaceNumber = self._objectRaw.attrs["module"]
        # IFaceNumber-Values:
        # IF1 = Master
        IFacePortNo = int(self._objectRaw.attrs["input"]) - 159
        # IFacePortNo-Values:
        # I1 = 160
        # I2 = 161
        # …
        # I8 = 167
        IFacePortMode = int(self._objectRaw.attrs["inputMode"])
        # IFacePortMode-Values:
        # 0  = D 10V   Sensor-Type  6   (Spursensor)
        # 1  = D 5k    Sensor-Types 1-3 (Taster, Fototransitor, Reed-Kontakt)
        # 3  = A 10V   Sensor-Type  8   (Farbsensor)
        # 4  = A 5k    Sensor-Types 4-5 (NTC-Widerstand, Fotowiderstand)
        # 10 = Ultra…  Sensor-Type  7   (Abstandssensor)
        return IFaceNumber, IFacePortNo, IFacePortMode

    def _findPin(self, pinID):
        """
        The _findPin-Function takes an inputID and returns the pin-object of the
        given Pin-ID. If no corresponding pin is found it returns none.
        """
        for pin in self._pins:
            if pin["id"] == pinID:
                return pin
        return None