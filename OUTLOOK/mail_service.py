# -*- coding: utf-8 -*-
"""MSAL abre Microsoft en el navegador. El usuario otorga permisos cuando hacen falta."""
from core import OutlookService,SCOPES

class MailService(OutlookService):
    def connect_interactive(self,email):
        # Reutilizar sesión cifrada de Windows cuando Microsoft la permita.
        try:
            if self.token(email): return True
        except (RuntimeError,ValueError):
            pass
        with self.lock:
            result=self.app.acquire_token_interactive(scopes=SCOPES,login_hint=email,
                domain_hint='consumers',timeout=240)
        if not result or 'access_token' not in result:
            raise RuntimeError('No se completó el acceso en Microsoft: '+str((result or {}).get('error_description','sin detalles'))[:200])
        actual=self._request(result['access_token'],'/me',{'$select':'mail,userPrincipalName'})
        known={str(v).casefold() for v in (
            actual.get('mail'),actual.get('userPrincipalName'),
            (result.get('id_token_claims') or {}).get('preferred_username')) if v}
        if email.casefold() not in known or not self.account(email):
            raise RuntimeError('La sesión autorizada no coincide con la cuenta seleccionada. Revisa qué cuenta elegiste en Microsoft.')
        return True
