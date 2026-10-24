import os,json,time,urllib.request,base64,traceback
from pathlib import Path
out=Path('qa-ios-evidence');out.mkdir(exist_ok=True)
base='http://127.0.0.1:4723';session=None
def call(method,path,body=None):
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'},method=method)
    try:
        with urllib.request.urlopen(req,timeout=240) as r: result=json.load(r)
    except urllib.error.HTTPError as e: raise RuntimeError(e.read().decode())
    value=result.get('value')
    if isinstance(value,dict) and 'error' in value: raise RuntimeError(str(value))
    return value
def cmd(method,path,body=None): return call(method,'/session/'+session+path,body)
try:
    caps={'platformName':'iOS','browserName':'Safari','appium:automationName':'XCUITest','appium:udid':Path('qa-ios-evidence/udid.txt').read_text().strip(),'appium:showXcodeLog':True,'appium:includeSafariInWebviews':True,'appium:connectHardwareKeyboard':False,'appium:forceSimulatorSoftwareKeyboardPresence':True,'appium:newCommandTimeout':180,'appium:wdaLaunchTimeout':180000,'appium:safariInitialUrl':'https://funji713.github.io/1a2b-invite/'}
    value=call('POST','/session',{'capabilities':{'alwaysMatch':caps}})
    session=value['sessionId']
    print('APPIUM_SESSION_READY',flush=True)
    cmd('POST','/url',{'url':'https://funji713.github.io/1a2b-invite/'})
    time.sleep(30)
    contexts=cmd('GET','/contexts')
    out.joinpath('contexts.json').write_text(json.dumps(contexts,indent=2))
    state=cmd('POST','/execute/sync',{'script':'return {href:location.href,ua:navigator.userAgent,inner:[innerWidth,innerHeight],canvas:document.querySelector("canvas")?.getBoundingClientRect().toJSON(),engine:typeof Engine,standalone:navigator.standalone};','args':[]})
    out.joinpath('browser.json').write_text(json.dumps(state,indent=2))
    out.joinpath('safari.png').write_bytes(base64.b64decode(cmd('GET','/screenshot')))
    cmd('POST','/context',{'name':'NATIVE_APP'})
    out.joinpath('native-source.xml').write_text(cmd('GET','/source'))
    out.joinpath('native-safari.png').write_bytes(base64.b64decode(cmd('GET','/screenshot')))
    assert state['canvas'] and state['engine']=='function',state
    out.joinpath('result.json').write_text(json.dumps({'passed':True,'state':state},indent=2))
    print('IOS_SAFARI_ACTUAL_GAME_LOADED',flush=True)
except Exception:
    out.joinpath('error.txt').write_text(traceback.format_exc())
    if session:
        try: out.joinpath('failure.png').write_bytes(base64.b64decode(cmd('GET','/screenshot')))
        except Exception: pass
    raise
finally:
    if session:
        try:cmd('DELETE','')
        except Exception:pass
