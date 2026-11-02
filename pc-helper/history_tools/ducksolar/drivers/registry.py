from .daxtromn import DaxtromnPI30Driver

DRIVERS = {DaxtromnPI30Driver.id: DaxtromnPI30Driver}

def create_driver(profile_id, cfg):
    try: factory = DRIVERS[profile_id]
    except KeyError: raise ValueError('Unsupported inverter profile: ' + str(profile_id))
    return factory(cfg)



def inspect_payload(frame, command=None):
    # Observational decoding is profile-specific and never gates raw forwarding.
    if int.from_bytes(frame[2:4],'big') != DaxtromnPI30Driver.device_code: return {}
    from ..protocol.pi30 import decode_packet, extract_command_name, parse_qpigs
    from dataclasses import asdict
    payload=frame[8:];raw=decode_packet(payload)
    name=extract_command_name(payload)
    decoded={'crc_valid':True,'packet_type':'response' if raw.startswith(b'(') else 'command'}
    if command=='QPIGS' and raw.startswith(b'('): decoded.update(asdict(parse_qpigs(raw[1:].decode('ascii'))))
    return {'command':command or name,'pi30_command':command or name,'profile':DaxtromnPI30Driver.id,
            'decoded_fields':{'transaction_id':int.from_bytes(frame[:2],'big'),'device':frame[2:4].hex(),
                              'address':frame[6],'function':frame[7],**decoded}}
