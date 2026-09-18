"""Tunel SSH para desarrollo local: expone MySQL/Evolution API/Chatwoot del
server nuevo (2.24.139.178) en localhost, sin abrir esos puertos a internet.

Uso: python dev_tunnel.py
(requiere la variable de entorno SSH_PASS con la contraseña root del server)
"""

import os
import select
import socket
import sys
import threading

import paramiko

HOST = "2.24.139.178"
FORWARDS = [
    (3306, 3306),   # MySQL de LiveShop
    (8080, 8080),   # Evolution API
    (3010, 3010),   # Chatwoot
]


def forward_tunnel(local_port, remote_host, remote_port, transport):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                chan = transport.open_channel(
                    "direct-tcpip",
                    (remote_host, remote_port),
                    self.request.getsockname(),
                )
            except Exception as e:
                print(f"[{local_port}] no se pudo abrir el canal: {e}")
                return
            if chan is None:
                return
            while True:
                r, w, x = select.select([self.request, chan], [], [])
                if self.request in r:
                    data = self.request.recv(4096)
                    if len(data) == 0:
                        break
                    chan.send(data)
                if chan in r:
                    data = chan.recv(4096)
                    if len(data) == 0:
                        break
                    self.request.send(data)
            chan.close()
            self.request.close()

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = Server(("127.0.0.1", local_port), Handler)
    server.serve_forever()


import socketserver  # noqa: E402


def main():
    password = os.environ.get("SSH_PASS")
    if not password:
        print("Falta la variable de entorno SSH_PASS")
        sys.exit(1)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=password, timeout=20)
    transport = client.get_transport()

    print(f"Tunel abierto hacia {HOST}. Forwards:")
    threads = []
    for local_port, remote_port in FORWARDS:
        print(f"  localhost:{local_port} -> {HOST}:{remote_port}")
        t = threading.Thread(
            target=forward_tunnel,
            args=(local_port, "127.0.0.1", remote_port, transport),
            daemon=True,
        )
        t.start()
        threads.append(t)

    print("Ctrl+C para cerrar.")
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
