import asyncio
import logging
import time

_LOGGER = logging.getLogger(__name__)
# Default timeout 101 sec for keepalive packet, if exceeded then plug is dead and should be removed
DEFAULT_TIMEOUT = 101
# Default provisioning server port
DEFAULT_PORT = 1822

class TendaBeliPlug():
    def __init__(self, address :str , writer, *args,
                 timeout=DEFAULT_TIMEOUT):
        self._availible = False
         # Connection to provisioning server
        self._ip_address = address
        self._writer = writer
        self._timeout = timeout
        self._registration_date: time = time.time()
        self._last_alive = self._registration_date
        self._op_callbacks = set()
        
        # Plug Identification Data - obtained from first packet
        self._sn = None
        self._nick = None
        
        # Plug Operating Data
        self._is_on = False
        self._power: str =  "unknown"
        self._power_last_update: time = None
        self._energy: str = "unknown"
        self._energy_last_update: time = None
        
    def send_toggle_request(self)-> None:
        self._writer.write(bytes.fromhex("24000300015d000c000000005f0c00007b22616374696f6e223a317d"))   

    def send_power_request(self)-> None:
        self._writer.write(bytes.fromhex("2400030000d500000205000000000000"))   

    def send_consume_request(self)-> None:
        self._writer.write(bytes.fromhex("2400030000d500000208000000000000"))

    async def update_hass(self)-> None:
        for callback in self._op_callbacks:
            await callback()

    def op_callbacks(self, callback, discard: bool = False) -> None:
        self._op_callbacks.discard(callback) if discard else self._op_callbacks.add(callback)

    @property
    def alive(self) -> bool:
        return False if (time.time() - self._last_alive) > self._timeout else True
    @alive.setter
    def alive(self,value :time):
        self._last_alive = value 

    @property
    def ip_address(self) -> str:
        return self._ip_address
    
    @property  
    def sn(self) -> str:
        return self._sn
    @sn.setter
    def sn(self, value: str):
        self._sn = value
       
    @property
    def nick(self) -> str:
        return self._nick
    @nick.setter
    def nick(self, value: str):
        self._nick = value
    
    @property
    def is_on(self) -> bool:
        return self._is_on
    @is_on.setter
    def is_on(self, value: bool):
        self._is_on = value
        asyncio.create_task(self.update_hass())

    @property
    def power(self)-> str:
        return self._power
    @power.setter
    def power(self,value: str):
        self._power = value
        self._power_last_update = time.time()
        asyncio.create_task(self.update_hass())

    @property
    def energy(self)-> str:
        return self._energy
    @energy.setter
    def energy(self,value: str):
        self._energy = value
        self._energy_last_update = time.time() 
        asyncio.create_task(self.update_hass())
    
    
class TendaBeliServer:
    def __init__(self):

        self._running = False
        self._servers = []
        self._connected_plugs = {}
        self._stp_callbacks = set()
                
        self._prov_srv_ip: str = "" 
        asyncio.create_task(self.plug_health_check())

    @property
    def get_connected_plugs(self):
        return self._connected_plugs
    
    def get_TBP(self, uid)-> TendaBeliPlug:
        return next((plug for plug in self._connected_plugs.values() if plug.sn == uid), None)
    
    async def plug_health_check(self):
        while True:
            try:
                pop_plugs = []
                plug: TendaBeliPlug = None
                for key, plug in self._connected_plugs.items():
                    if not plug.alive:
                        await plug.update_hass()
                        pop_plugs.append(key)
                        _LOGGER.debug(f"{plug.sn} is not more live, will be removed")
                    else:
                        _LOGGER.debug(f"{plug.sn} is still active")

                for key in pop_plugs:
                    self._connected_plugs.pop(key)

            except Exception as err:
                _LOGGER.info(f"Unexpected {err=}, {type(err)=} durig plug health check!")
            await asyncio.sleep(DEFAULT_TIMEOUT+10)

    def register_operational_callback(self, callback, _sn):
        plug: TendaBeliPlug = None
        for plug in self._connected_plugs.values():
            if plug.sn == _sn:
                plug.op_callbacks(callback)
    
    def remove_operational_callback(self, callback, _sn):
        plug: TendaBeliPlug = None
        for plug in self._connected_plugs.values():
            if plug.sn == _sn:
                plug.op_callbacks(callback, True)

    def register_setup_callback(self, callback):
        self._stp_callbacks.add(callback)
    
    def remove_setup_callback(self, callback):
        self._stp_callbacks.discard(callback)

    async def listen(self, haIp):
        _haIP = haIp.split(".")
        if len(_haIP) == 4:
            self._prov_srv_ip = "".join(map(lambda x: format(int(x), "02x"), _haIP))
            asyncio.create_task(self.start(1821,self.handle_rendezvous_connection))
            asyncio.create_task(self.start(DEFAULT_PORT,self.handle_provisioning_connection))
            self._running = True
        else:
             _LOGGER.debug(f"Not valid IP: {haIp}")


    async def start(self, port, handle):
        server = await asyncio.start_server(handle, "0.0.0.0", port)
        self._servers.append(server)
        addr = server.sockets[0].getsockname()
        _LOGGER.debug(f"Server listening on {addr}:{port}")
        async with server:
            await server.serve_forever()
        

    async def stop(self):
        self._running = False
        # for callback in self._op_callbacks:
        #     await callback(f"{plug.sn}", "update")
        # for callback in self._stp_callbacks:
        #     await callback(f"{plug.sn}", "discard")
        _LOGGER.debug("Stop called. Closing connection")
        for server in self._servers:
            server.close()    

    async def handle_rendezvous_connection(self, reader, writer):
        """ Parse packets from plugs """
        try: 
            address, port = writer.get_extra_info('peername')
            _LOGGER.info(f"Plug {address} succesfully connected to rendezvous server")
            writer.write(bytes.fromhex(f"2400020000d2000e000000000000000000100004{self._prov_srv_ip}00110002{int(DEFAULT_PORT):04x}"))
        except Exception as err:
            _LOGGER.info(f"Unexpected {err=}, {type(err)=} during rendezvous porting at {str(int(time.time()))} !")    

    async def handle_provisioning_connection(self, reader, writer):
        """ Parse packets from plugs """
        try:
            address, port = writer.get_extra_info('peername')
            self._connected_plugs[address] = TendaBeliPlug(address, writer)

            _LOGGER.info(f"Plug {address} succesfully redirected to provisioning server")
            data = await reader.read(1024)
            writer.write(bytes.fromhex("24000300001a001d0000000000000000000700010000080001000009000100000a00020064000b000400015180"))
            data = await reader.read(1024)
            
            connected = True
            while connected:
                datapack = await reader.read(1024)
                if datapack:
                    datapack = datapack.split(b'$')
                    for data in datapack:
                        if len(data) > 0:
                              
                            _LOGGER.info(f"Recieved Packet: {data}")
                            
                            # keepalive packet recieved
                            if data[4] == 101 : #0x65
                                writer.write(bytes.fromhex("24000300006600000000000000000000"))
                                self._connected_plugs[address].alive = time.time()
                                self._connected_plugs[address].send_power_request()
                                _LOGGER.debug(f"Keepalive packet recieved, ack send.")

                            # on/off status packet recieved (with serial num identification)
                            # {"serialNum":"E9641010034003223","status":1}'
                            elif data[4] == 102 : #0x66
                                if len(data) == 59:
                                    snIdx = data.rfind(b'serialNum')
                                    new_sn = (data[snIdx+12:snIdx+29].decode('utf-8'))
                                    self._connected_plugs[address].is_on = True if data[57] == 49 else False
                                    self._connected_plugs[address].send_power_request()
                                    _LOGGER.debug(f"Got Switch Status for: {self._connected_plugs[address].sn} = {self._connected_plugs[address].is_on}")
                                   
                                    if self._connected_plugs[address].sn != new_sn:
                                        self._connected_plugs[address].sn = new_sn
                                        _LOGGER.debug(f"Plug {self._connected_plugs[address].sn} initializing") 
                                        for callback in self._stp_callbacks:
                                            await callback(f"{self._connected_plugs[address].sn}", "setup")
                                    

                            #plug ack when command was recieved
                            #b'\x00\x06\x00\x01^\x00#\x03:\x00\x00_\x0c\x00\x00{"resp_code":0,"data":{"status":1}}'
                            # 15 + 
                            elif data[4] == 94 : #^
                                if len(data) == 55:
                                    #self._connected_plugs[address].is_on = True if data[53] == 49 else False
                                    _LOGGER.debug(f"Got command rensponse for: {self._connected_plugs[address].sn} = {self._connected_plugs[address].is_on}")

                            # serial number packet recieved
                            # {"serialNum":"E9641010034003225","mark":"","time_zone":0,"location":"Europe/Prague"}'            
                            elif data[4] == 103 : #0x65
                                snIdx = data.rfind(b'serialNum')
                                new_sn = (data[snIdx+12:snIdx+29].decode('utf-8'))
                                
                                if self._connected_plugs[address].sn != new_sn:
                                    self._connected_plugs[address].sn = new_sn
                                    _LOGGER.debug(f"Plug {self._connected_plugs[address].sn} initializing") 
                                    for callback in self._stp_callbacks:
                                        await callback(f"{self._connected_plugs[address].sn}", "setup")

                            elif data[4] ==  213: #0xd5
                                if len(data) > 50:
                                    powStr = str(data)[-15:-3]
                                    powStr = powStr[powStr.rfind(':')+1:]
                                    self._connected_plugs[address].power = powStr
                                    _LOGGER.debug(f"Got Actual Power Draw for: {self._connected_plugs[address].sn} = {self._connected_plugs[address].power}")
                            
                            # electricity consumption packet recieved
                            #b'\x00\x06\x00\x01\x89\x007\x03E\x00\x00\x00\x00\x00\x00{"ver":3,"energy":["1688828405,200677,2.220,128987,0"]}'
                            #b'\x00\x06\x00\x01\x89\x01\xb8\x03E\x00\x00\x00\x00\x00\x00{"ver":3,"energy":["1688943601,318626,2.930,163494,0","1688947201,322309,2.930,163494,0","1688950800,325992,2.930,163494,0","1688954404,329680,2.930,163494,0","1688958001,333360,2.930,163494,0","1688961603,337088,2.930,163494,0","1688965204,340772,2.930,163494,0","1688968801,344454,2.930,163494,0","1688972404,348140,2.940,163494,0","1688976005,351824,2.940,163494,0","1688979600,355503,2.940,163494,0","1688983201,359188,2.980,165864,0"]}'
                            elif data[4] ==  137: #0x89
                                writer.write(bytes.fromhex("24000300018c000400000000000000006e756c6c"))
                                if len(data) > 37:
                                    consumeRaw = str(data[data.rfind(b'energy')+10:-4])
                                    consumeRaw = consumeRaw.replace("\"", "")
                                    consumeRaw = consumeRaw.split(",")
                                    dataCnt = len(consumeRaw)
                                    #rotate for serveral consume frames
                                    if dataCnt % 5 == 0:
                                        if dataCnt / 5 == 2:
                                            if consumeRaw[1] == consumeRaw[6]:
                                                self._connected_plugs[address].energy = consumeRaw[2]
                                                _LOGGER.debug(f"Got Overall Consumption: {address} = {consumeRaw[2]}")
                                        else:
                                            if data.rfind(b'ver') > 0:
                                                for i in range(0, dataCnt, 5) :
                                                    self._connected_plugs[address].energy = consumeRaw[2]
                                                    _LOGGER.debug(f"Got Overall Consumption: {address} = {consumeRaw[2]}")
                            
                            #Unknow message
                            #b'\x00\x06\x00\x01\x81\x00\x00\x03D\x00\x00_\x0c\x00\x00'

                            else:
                                _LOGGER.debug(f"Unknown Packet: {data}")
                  
        except Exception as err:
            _LOGGER.debug(f"Unexpected {err=}, {type(err)=} at {str(int(time.time()))} !")                    
            
  