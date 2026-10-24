# -*- coding: utf-8 -*-
"""Prueba local SIN abrir cuentas ni celular. No utiliza contraseñas."""
from enlace import Server,State,Client,LinkError
import secrets

def main():
    # Puerto temporal para no interferir con la sesión real de Outlook.
    s=State();server=Server(s,port=0);server.start()
    client=Client(port=server.server.server_address[1])
    try:
        assert client.ping()['ok']
        req=secrets.token_hex(16)
        d=client.begin('prueba@example.com',req)
        assert d['status']=='ESPERANDO_CODIGO'
        try: s.put_code(req,'123456','distinto@example.com')
        except ValueError:pass
        else:raise AssertionError('Debe bloquear correos diferentes')
        s.put_code(req,'001234',email='prueba@example.com')
        assert client.status(req)['code']=='001234'
        client.ack(req)
        assert client.status(req)['code'] is None
        client.done(req)
        assert client.status(req)['status']=='SOLICITUD_IMSS_ENVIADA'
        print('OK: enlace local, cuentas, código con cero inicial, confirmación, fin.')
    finally:server.close()

if __name__=='__main__':main()
