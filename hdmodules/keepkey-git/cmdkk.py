#!/usr/bin/env python

# This file is part of the TREZOR project.
#
# Copyright (C) 2012-2016 Marek Palatinus <slush@satoshilabs.com>
# Copyright (C) 2012-2016 Pavol Rusnak <stick@satoshilabs.com>
# Copyright (C) 2016      Jochen Hoenicke <hoenicke@gmail.com>
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library.  If not, see <http://www.gnu.org/licenses/>.
#
# The script has been modified for KeepKey Device.
 
from __future__ import print_function
import os
import binascii
import argparse
import json
import base64
import urllib
import tempfile

from keepkeylib.client import KeepKeyClient, KeepKeyClientDebug
import keepkeylib.types_pb2 as types

def parse_args(commands):
    parser = argparse.ArgumentParser(description='Commandline tool for KeepKey devices.')
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Prints communication to device')
    parser.add_argument('-t', '--transport', dest='transport',  choices=['usb', 'serial', 'pipe', 'socket', 'bridge'], default='usb', help="Transport used for talking with the device")
    parser.add_argument('-p', '--path', dest='path', default='', help="Path used by the transport (usually serial port)")
#    parser.add_argument('-dt', '--debuglink-transport', dest='debuglink_transport', choices=['usb', 'serial', 'pipe', 'socket'], default='usb', help="Debuglink transport")
#    parser.add_argument('-dp', '--debuglink-path', dest='debuglink_path', default='', help="Path used by the transport (usually serial port)")
    parser.add_argument('-j', '--json', dest='json', action='store_true', help="Prints result as json object")
#    parser.add_argument('-d', '--debug', dest='debug', action='store_true', help='Enable low-level debugging')

    cmdparser = parser.add_subparsers(title='Available commands')

    for cmd in commands._list_commands():
        func = object.__getattribute__(commands, cmd)

        try:
            arguments = func.arguments
        except AttributeError:
            arguments = ((('params',), {'nargs': '*'}),)

        item = cmdparser.add_parser(cmd, help=func.help)
        for arg in arguments:
            item.add_argument(*arg[0], **arg[1])

        item.set_defaults(func=func)
        item.set_defaults(cmd=cmd)

    return parser.parse_args()

def get_transport(transport_string, path, **kwargs):
    if transport_string == 'usb':
        from keepkeylib.transport_hid import HidTransport

        if path == '':
            try:
                path = list_usb()[0][0]
            except IndexError:
                raise Exception("No KeepKey found on USB")

        for d in HidTransport.enumerate():
            # Two-tuple of (normal_interface, debug_interface)
            if path in d:
                return HidTransport(d, **kwargs)

        raise Exception("Device not found")
 
    if transport_string == 'serial':
        from keepkeylib.transport_serial import SerialTransport
        return SerialTransport(path, **kwargs)

    if transport_string == 'pipe':
        from keepkeylib.transport_pipe import PipeTransport
        return PipeTransport(path, is_device=False, **kwargs)
    
    if transport_string == 'socket':
        from keepkeylib.transport_socket import SocketTransportClient
        return SocketTransportClient(path, **kwargs)
    
    if transport_string == 'fake':
        from keepkeylib.transport_fake import FakeTransport
        return FakeTransport(path, **kwargs)

    raise NotImplementedError("Unknown transport")

class Commands(object):
    def __init__(self, client):
        self.client = client

    @classmethod
    def _list_commands(cls):
        return [x for x in dir(cls) if not x.startswith('_')]

    def list(self, args):
        # Fake method for advertising 'list' command
        pass

    def get_address(self, args):
        address_n = self.client.expand_path(args.n)
        typemap = { 'address': types.SPENDADDRESS,
                    'segwit': types.SPENDWITNESS,
                    'p2shsegwit': types.SPENDP2SHWITNESS }
        script_type = typemap[args.script_type];
        return self.client.get_address(args.coin, address_n, args.show_display, script_type=script_type)

    def ethereum_get_address(self, args):
        address_n = self.client.expand_path(args.n)
        address = self.client.ethereum_get_address(address_n, args.show_display)
        return "0x%s" % (binascii.hexlify(address),)

    def ethereum_sign_tx(self, args):
        from ethjsonrpc import EthJsonRpc
        from ethjsonrpc.utils import hex_to_dec
        import rlp

        value = args.value
        if ' ' in value:
            value, unit = value.split(' ', 1)
            if unit.lower() not in ether_units:
                raise CallException(types.Failure_Other, "Unrecognized ether unit %r" % unit)
            value = int(value) * ether_units[unit.lower()]
        else:
            value = int(value)

        gas_price = args.gas_price
        if gas_price is not None:
            if ' ' in gas_price:
                gas_price, unit = gas_price.split(' ', 1)
                if unit.lower() not in ether_units:
                    raise CallException(types.Failure_Other, "Unrecognized gas price unit %r" % unit)
                gas_price = int(gas_price) * ether_units[unit.lower()]
            else:
                gas_price = int(gas_price)

        gas_limit = args.gas
        if gas_limit is not None:
            gas_limit = int(gas_limit)

        if args.to.startswith('0x') or args.to.startswith('0X'):
            to_address = args.to[2:].decode('hex')
        else:
            to_address = args.to.decode('hex')

        nonce = args.nonce
        if nonce:
            nonce = int(nonce)

        address_n = self.client.expand_path(args.n)
        address = "0x%s" % (binascii.hexlify(self.client.ethereum_get_address(address_n)),)

        if gas_price is None or gas_limit is None or nonce is None:
            host, port = args.host.split(':')
            eth = EthJsonRpc(host, int(port))

        if not args.data:
            args.data = ''
        elif args.data.startswith('0x'):
            args.data = args.data[2:]
        data = binascii.unhexlify(args.data)

        if gas_price is None:
            gas_price = eth.eth_gasPrice()

        if gas_limit is None:
            gas_limit = eth.eth_estimateGas(
                to_address=args.to,
                from_address=address,
                value=("0x%x" % value),
                data="0x"+args.data)

        if nonce is None:
            nonce = eth.eth_getTransactionCount(address)

        sig = self.client.ethereum_sign_tx(
            n=address_n,
            nonce=nonce,
            gas_price=gas_price,
            gas_limit=gas_limit,
            to=to_address,
            value=value,
            data=data,
            chain_id=args.chain_id)

        transaction = rlp.encode(
            (nonce, gas_price, gas_limit, to_address, value, data) + sig)
        tx_hex = '0x%s' % binascii.hexlify(transaction)

        if args.publish:
            tx_hash = eth.eth_sendRawTransaction(tx_hex)
            return 'Transaction published with ID: %s' % tx_hash
        else:
            return 'Signed raw transaction: %s' % tx_hex

    def get_entropy(self, args):
        return binascii.hexlify(self.client.get_entropy(args.size))

    def get_features(self, args):
        return self.client.features

    def list_coins(self, args):
        return [coin.coin_name for coin in self.client.features.coins]

    def ping(self, args):
        return self.client.ping(args.msg, button_protection=args.button_protection, pin_protection=args.pin_protection, passphrase_protection=args.passphrase_protection)

    def get_public_node(self, args):
        address_n = self.client.expand_path(args.n)
        return self.client.get_public_node(address_n, ecdsa_curve_name=args.curve, show_display=args.show_display)

    def set_label(self, args):
        return self.client.apply_settings(label=args.label)

    def clear_session(self, args):
        return self.client.clear_session()

    def change_pin(self, args):
        return self.client.change_pin(args.remove)

    def apply_policy(self, args):
        return self.client.apply_policy(args.policy_name, args.enabled)

    def wipe_device(self, args):
        return self.client.wipe_device()

    def recovery_device(self, args):
        return self.client.recovery_device(args.use_trezor_method, args.words, args.passphrase_protection,
                                    args.pin_protection, args.label, 'english')

    def load_device(self, args):
        if not args.mnemonic and not args.xprv:
            raise CallException(types.Failure_Other, "Please provide mnemonic or xprv")

        if args.mnemonic:
            mnemonic = ' '.join(args.mnemonic)
            return self.client.load_device_by_mnemonic(mnemonic, args.pin,
                                                       args.passphrase_protection,
                                                       args.label, 'english',
                                                       args.skip_checksum)
        else:
            return self.client.load_device_by_xprv(args.xprv, args.pin,
                                                   args.passphrase_protection,
                                                   args.label, 'english')

    def reset_device(self, args):
        return self.client.reset_device(True, args.strength, args.passphrase_protection,
                                        args.pin_protection, args.label, 'english')

    def sign_message(self, args):
        address_n = self.client.expand_path(args.n)
        ret = self.client.sign_message(args.coin, address_n, args.message)
        output = {
            'message': args.message,
            'address': ret.address,
            'signature': base64.b64encode(ret.signature)
        }
        return output

    def verify_message(self, args):
        signature = base64.b64decode(args.signature)
        return self.client.verify_message(args.coin, args.address, signature, args.message)

    def encrypt_message(self, args):
        pubkey = binascii.unhexlify(args.pubkey)
        address_n = self.client.expand_path(args.n)
        ret = self.client.encrypt_message(pubkey, args.message, args.display_only, args.coin, address_n)
        output = {
            'nonce': binascii.hexlify(ret.nonce),
            'message': binascii.hexlify(ret.message),
            'hmac': binascii.hexlify(ret.hmac),
            'payload': base64.b64encode(ret.nonce + ret.message + ret.hmac),
        }
        return output

    def decrypt_message(self, args):
        address_n = self.client.expand_path(args.n)
        payload = base64.b64decode(args.payload)
        nonce, message, msg_hmac = payload[:33], payload[33:-8], payload[-8:]
        ret = self.client.decrypt_message(address_n, nonce, message, msg_hmac)
        return ret

    def encrypt_keyvalue(self, args):
        address_n = self.client.expand_path(args.n)
        ret = self.client.encrypt_keyvalue(address_n, args.key, args.value)
        return binascii.hexlify(ret)

    def decrypt_keyvalue(self, args):
        address_n = self.client.expand_path(args.n)
        ret = self.client.decrypt_keyvalue(address_n, args.key, args.value.decode("hex"))
        return ret

    def firmware_update(self, args):
        if not args.file and not args.url:
            raise Exception("Must provide firmware filename or URL")

        if args.file:
            fp = open(args.file, 'r')
        elif args.url:
            print("Downloading from", args.url)
            resp = urllib.urlretrieve(args.url)
            fp = open(resp[0], 'r')
            urllib.urlcleanup() # We still keep file pointer open

        if fp.read(8) == '54525a52':
            print("Converting firmware to binary")

            fp.seek(0)
            fp_old = fp

            fp = tempfile.TemporaryFile()
            fp.write(binascii.unhexlify(fp_old.read()))

            fp_old.close()

        fp.seek(0)
        if fp.read(4) != 'KPKY':
            raise Exception("KeepKey firmware header expected")

        print("Please confirm action on device...")

        fp.seek(0)
        return self.client.firmware_update(fp=fp)

    list.help = 'List connected KeepKey USB devices'
    ping.help = 'Send ping message'
    get_address.help = 'Get Morningstar address in base58 encoding'
    ethereum_get_address.help = 'Get Ethereum address in hex encoding'
    ethereum_sign_tx.help = 'Sign (and optionally publish) Ethereum transaction'
    get_entropy.help = 'Get example entropy'
    get_features.help = 'Retrieve device features and settings'
    get_public_node.help = 'Get public node of given path'
    set_label.help = 'Set new wallet label'
    clear_session.help = 'Clear session (remove cached PIN, passphrase, etc.)'
    change_pin.help = 'Change new PIN or remove existing'
    apply_policy.help = 'Apply a policy'
    list_coins.help = 'List all supported coin types by the device'
    wipe_device.help = 'Reset device to factory defaults and remove all private data.'
    recovery_device.help = 'Start safe recovery workflow'
    load_device.help = 'Load custom configuration to the device'
    reset_device.help = 'Perform device setup and generate new seed'
    sign_message.help = 'Sign message using address of given path'
    verify_message.help = 'Verify message'
    encrypt_message.help = 'Encrypt message'
    decrypt_message.help = 'Decrypt message'
    encrypt_keyvalue.help = 'Encrypt value by given key and path'
    decrypt_keyvalue.help = 'Decrypt value by given key and path'
    firmware_update.help = 'Upload new firmware to device (must be in bootloader mode)'

    get_address.arguments = (
        (('-c', '--coin'), {'type': str, 'default': 'Morningstar'}),
        (('-n', '-address'), {'type': str}),
        (('-t', '--script-type'), {'type': str, 'choices': ['address', 'segwit', 'p2shsegwit'], 'default': 'address'}),
        (('-d', '--show-display'), {'action': 'store_true', 'default': False}),
    )

    ethereum_get_address.arguments = (
        (('-n', '-address'), {'type': str}),
        (('-d', '--show-display'), {'action': 'store_true', 'default': False}),
    )

    ethereum_sign_tx.arguments = (
        (('-a', '--host'), {'type': str, 'help': 'RPC port of ethereum node for automatic gas/nonce estimation', 'default': 'localhost:8545'}),
        (('-c', '--chain-id'), {'type' : int, 'help': 'EIP-155 chain id (replay protection)', 'default': None}),
        (('-n', '-address'), {'type': str, 'help': 'BIP-32 path to signing key'}),
        (('-v', '--value'), {'type': str, 'help': 'Ether amount to transfer, e.g., "100 milliether"', 'default': "0"}),
        (('-g', '--gas'), {'type': int, 'help': 'Gas limit - Required for offline signing', 'default': None}),
        (('-t', '--gas-price'), {'type': str, 'help': 'Gas price, e.g., "20 nanoether" - Required for offline signing', 'default': None }),
        (('-i', '--nonce'), {'type': int, 'help': 'Transaction counter - Required for offline signing', 'default': None}),
        (('-d', '--data'), {'type': str, 'help': 'Data as hex string, e.g., 0x12345678', 'default': ''}),
        (('-p', '--publish'), {'action': 'store_true', 'help': 'publish transaction via RPC', 'default': False}),
        (('to',), {'type': str, 'help': 'Destination address; "" for contract creation'}),
    )

    get_entropy.arguments = (
        (('size',), {'type': int}),
    )

    get_features.arguments = ()

    list_coins.arguments = ()

    ping.arguments = (
        (('msg',), {'type': str}),
        (('-b', '--button-protection'), {'action': 'store_true', 'default': False}),
        (('-p', '--pin-protection'), {'action': 'store_true', 'default': False}),
        (('-r', '--passphrase-protection'), {'action': 'store_true', 'default': False}),
    )

    set_label.arguments = (
        (('-l', '--label',), {'type': str, 'default': ''}),
        # (('-c', '--clear'), {'action': 'store_true', 'default': False})
    )

    change_pin.arguments = (
        (('-r', '--remove'), {'action': 'store_true', 'default': False}),
    )

    apply_policy.arguments = (
        (('-o', '--policy-name'), {'type': str, 'default': ''}),
        (('-c', '--enabled'), {'action': 'store_true', 'default': False}),
    )

    wipe_device.arguments = ()

    recovery_device.arguments = (
        (('-w', '--words'), {'type': int, 'choices': [12, 18, 24], 'default': 24}),
        (('-p', '--pin-protection'), {'action': 'store_true', 'default': False}),
        (('-r', '--passphrase-protection'), {'action': 'store_true', 'default': False}),
        (('-l', '--label'), {'type': str, 'default': ''}),
        (('-t', '--use-trezor-method'), {'action': 'store_true', 'default': False}),
    )

    load_device.arguments = (
        (('-m', '--mnemonic'), {'type': str, 'nargs': '+'}),
        (('-x', '--xprv'), {'type': str}),
        (('-p', '--pin'), {'type': str, 'default': ''}),
        (('-r', '--passphrase-protection'), {'action': 'store_true', 'default': False}),
        (('-l', '--label'), {'type': str, 'default': ''}),
        (('-s', '--skip-checksum'), {'action': 'store_true', 'default': False}),
    )

    reset_device.arguments = (
        (('-t', '--strength'), {'type': int, 'choices': [128, 192, 256], 'default': 256}),
        (('-p', '--pin-protection'), {'action': 'store_true', 'default': False}),
        (('-r', '--passphrase-protection'), {'action': 'store_true', 'default': False}),
        (('-l', '--label'), {'type': str, 'default': ''}),
    )

    sign_message.arguments = (
        (('-c', '--coin'), {'type': str, 'default': 'morningstar'}),
        (('-n', '-address'), {'type': str}),
        (('message',), {'type': str}),
    )

    encrypt_message.arguments = (
        (('pubkey',), {'type': str}),
        (('message',), {'type': str}),
        (('-d', '--display-only'), {'action': 'store_true', 'default': False}),
        (('-c', '--coin'), {'type': str, 'default': 'morningstar'}),
        (('-n', '-address'), {'type': str}),
    )

    decrypt_message.arguments = (
        (('-n', '-address'), {'type': str}),
        (('payload',), {'type': str}),
    )

    verify_message.arguments = (
        (('-c', '--coin'), {'type': str, 'default': 'morningstar'}),
        (('address',), {'type': str}),
        (('signature',), {'type': str}),
        (('message',), {'type': str}),
    )

    encrypt_keyvalue.arguments = (
        (('-n', '-address'), {'type': str}),
        (('key',), {'type': str}),
        (('value',), {'type': str}),
    )

    decrypt_keyvalue.arguments = (
        (('-n', '-address'), {'type': str}),
        (('key',), {'type': str}),
        (('value',), {'type': str}),
    )

    get_public_node.arguments = (
        (('-n', '-address'), {'type': str}),
        (('-e', '--curve'), {'type': str}),
        (('-d', '--show-display'), {'action': 'store_true', 'default': False}),
    )

    firmware_update.arguments = (
        (('-f', '--file'), {'type': str}),
        (('-u', '--url'), {'type': str}),
    )

def list_usb():
    from keepkeylib.transport_hid import HidTransport
    return HidTransport.enumerate()

def main():
    args = parse_args(Commands)

    if args.cmd == 'list':
        devices = list_usb()
        if args.json:
            print(json.dumps(devices))
        else:
            for dev in devices:
                if dev[1] != None:
                    print("%s - debuglink enabled" % dev[0])
                else:
                    print(dev[0])
        return

    transport = get_transport(args.transport, args.path)
    if args.verbose:
        client = KeepKeyClientDebug(transport)
    else:
        client = KeepKeyClient(transport)

    cmds = Commands(client)

    res = args.func(cmds, args)

    if args.json:
        print(json.dumps(res, sort_keys=True, indent=4))
    else:
        print(res)

if __name__ == '__main__':
    main()
