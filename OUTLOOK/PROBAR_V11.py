from pathlib import Path
from tempfile import TemporaryDirectory
from credenciales import parse_list, Vault
from queue_store import QueueStore
from cooldown import Cooldown

clock=[200.]
c=Cooldown(60,clock=lambda:clock[0]);c.begin();assert c.remaining()==60
clock[0]+=29.5;assert c.remaining()==31
clock[0]+=31;assert c.remaining()==0
parsed=parse_list('uno@hotmail.com | CONTRA: demo.abc\ndos@outlook.com:Clave.124\n')
assert len(parsed)==2 and parsed[0][1]=='demo.abc' and parsed[1][1]=='Clave.124'
class DummyDPAPI:
 def protect(self,x):return ('ENC:'+x).encode()
 def unprotect(self,x):return x.decode().removeprefix('ENC:')
with TemporaryDirectory() as tmp:
 v=Vault(protector=DummyDPAPI(),path=Path(tmp)/'v.sqlite3')
 v.save(parsed)
 assert v.password('uno@hotmail.com')=='demo.abc'
 q=QueueStore(path=Path(tmp)/'q.sqlite3')
 assert q.add([e for e,_ in parsed])==2
 q.select_all()
 assert q.choose()=='uno@hotmail.com'
 q.mark_started('uno@hotmail.com')
 assert q.choose()=='dos@outlook.com'
assert Path(__file__).parent.joinpath('app.py').exists()
print('V11/V12: pruebas de cooldown, importación, cifrado y cola SUPERADAS')
