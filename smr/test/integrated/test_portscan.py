#
# Copyright 2020 Naver Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import unittest
import time
import socket
import Cm, Pg, Pgs, Smr, Conn, Util

class TestPortScan (unittest.TestCase):

    def _check_conn_blocked(self):
        st = time.time()
        for i in range(40):
            ok = True
            try:
                conn = Conn.Conn('localhost', 1900+(i%4))
                resp = conn.do_request('ping')
            except:
                ok = False
            if ok:
                raise Exception("Not blocked")
        et = time.time()
        if et - st > 1.0:
            raise Exception("10 connection try exceeds 1.0 sec.")

    def test_portscan(self):
        cm = None
        pgs = None
        try:
            cm = Cm.CM("test_portscan")
            cm.create_workspace()
            pg = Pg.PG(0)

            # pgs --> master
            pgs = Pgs.PGS(0, 'localhost', 1900, cm.dir)
            pg.join(pgs, start=True)
            pgs.smr.wait_role(Smr.SMR.MASTER)

            # -----------------------------------------
            # Test bad handshake blocks IP temporarily
            # -----------------------------------------
            for off in range(0,3):
                # bad handshake
                try:
                    conn = Conn.Conn('localhost', 1900+off)
                    resp = conn.do_request('ping')
                except:
                    pass
                self._check_conn_blocked()

            # wait for block released
            time.sleep(2.0) # actually 1.5 sec

            # -------------------------------------------------------
            # Can't connect mgmt port SMR_MAX_MGMT_CLIENTS_PER_IP(50)
            # -------------------------------------------------------
            conns = []
            for i in range(50-1): # -1
                conn = Conn.Conn('localhost', 1903)
                resp = conn.do_request('ping')
                assert(len(resp) == 1 and resp[0].startswith('+OK')), resp
                conns.append(conn)
            self._check_conn_blocked()

        finally:
            if pgs is not None:
                pgs.kill_smr()
                pgs.kill_be()
            if cm is not None:
                cm.remove_workspace()

    def make_sock(self, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(10)
        sock.connect((host, port))
        return sock

    def local_handshake(self, host, port):
        seq = b'\x00\x00\x00\x00\x00\x00\x00\x00'
        timeout = 1.0
        st = time.time()
        sock = self.make_sock(host, port)
        try:
            sock.settimeout(timeout+0.1)
            sock.sendall(seq)
            d = sock.recv(1)
            sock.close()
            if len(d) == 0:
                return False
            return True
        except Exception as e:
            sock.close()
            et = time.time()
            if et-st > timeout:
                return True
            return False

    def client_handshake(self, host, port, nid):
        sock = self.make_sock(host, port)
        timeout = 1.0
        try:
            sock.settimeout(timeout+0.1)
            sock.sendall(nid)
            d = sock.recv(8) # committed seq
            sock.close()
            if len(d) == 8:
                return True
            return False
        except Exception as e:
            sock.close()
            return False

    def test_portscan2(self):
        cm = None
        pgs = None
        myip = socket.gethostbyname(socket.gethostname())
        try:
            cm = Cm.CM("test_portscan2")
            cm.create_workspace()
            pg = Pg.PG(0)

            pgs = Pgs.PGS(0, 'localhost', 1900, cm.dir)
            pgs.start_smr()
            pgs.smr.wait_role(Smr.SMR.NONE)

            # ****NONE here
            # local connection ok case
            ok = self.local_handshake("localhost", 1900)
            assert ok, ok
            # local connection bad case (immediate failure)
            ok = self.local_handshake(myip, 1900)
            assert not ok, ok
            time.sleep(1.6) # this line matters (SMR_ACCEPT_BLOCK_MSEC 1500)

            pgs.start_be()
            pgs.smr.wait_role(Smr.SMR.LCONN)

            # ****LCONN here
            pg.join(pgs, start = False)

            # ****MASTER here
            # case sc: None, cc: nid == 0, but not local loopback address
            ok = self.client_handshake(myip, 1901, b'\x00\x00')
            assert not ok, ok
            time.sleep(1.6) # this line matters (SMR_ACCEPT_BLOCK_MSEC 1500)
            # sc: myip, cc: local loopback
            sc = None
            try:
                # make slave connection
                sc = self.make_sock(myip, 1902)
                sc.settimeout(1.0)
                min_seq = sc.recv(8)
                assert len(min_seq) == 8, min_seq
                commit_seq = sc.recv(8)
                assert len(commit_seq) == 8, commit_seq
                max_seq = sc.recv(8)
                assert len(max_seq) == 8, max_seq
                sc.sendall(b'\x00\x01')
                sc.sendall(b'\x00\x00\x00\x00\x00\x00\x00\x00')
                time.sleep(0.1)
            except Exception as e:
                if sc != None:
                    sc.close()
                    sc = None
            assert sc != None, sc

            ok = self.client_handshake("localhost", 1901, b'\x00\x01')
            assert not ok, ok
            sc.close()
            time.sleep(1.6) # this line matters (SMR_ACCEPT_BLOCK_MSEC 1500)
        finally:
            if pgs is not None:
                pgs.kill_smr()
                pgs.kill_be()
            if cm is not None:
                cm.remove_workspace()

if __name__ == '__main__':
    unittest.main()
