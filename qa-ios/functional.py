import os,json,time,urllib.request,urllib.error,base64,traceback,subprocess,re
from pathlib import Path
out=Path('qa-ios-evidence');out.mkdir(exist_ok=True)
base='http://127.0.0.1:4723';session=None;web=None;code=None
root='https://funji713.github.io/1a2b-invite/'
report={'checks':[],'phase':'startup'}
def save():out.joinpath('functional-result.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
def call(method,path,body=None,timeout=None):
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'},method=method)
    try:
        with urllib.request.urlopen(req,timeout=timeout or (420 if path=='/session' else 35)) as r:result=json.load(r)
    except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode())
    value=result.get('value')
    if isinstance(value,dict) and 'error' in value:raise RuntimeError(str(value))
    return value
def cmd(method,path,body=None,timeout=None):return call(method,'/session/'+session+path,body,timeout)
def execute(script,args=None):return cmd('POST','/execute/sync',{'script':script,'args':args or []})
def native():cmd('POST','/context',{'name':'NATIVE_APP'})
def webview():
    global web
    if web:cmd('POST','/context',{'name':web});return
    for attempt in range(8):
        contexts=cmd('GET','/contexts');out.joinpath('contexts.json').write_text(json.dumps(contexts,indent=2))
        candidates=[x for x in contexts if x!='NATIVE_APP']
        if candidates:
            web=candidates[-1];cmd('POST','/context',{'name':web});return
        time.sleep(4)
    raise AssertionError('No actual Safari web context')
def check(name,condition,details=None):
    report['checks'].append({'name':name,'passed':bool(condition),'details':details});save()
    assert condition,name
def capture(label,ocr=False):
    native()
    path=out/(label+'.png');path.write_bytes(base64.b64decode(cmd('GET','/screenshot')))
    out.joinpath(label+'.xml').write_text(cmd('GET','/source'))
    if ocr:
        rows=json.loads(subprocess.check_output(['./qa-ios/ocr',str(path)],timeout=40))
        out.joinpath(label+'-ocr.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False));return rows
def find_native(label,contains=False):
    native();operator='CONTAINS' if contains else '=='
    result=cmd('POST','/elements',{'using':'-ios predicate string','value':f'label {operator} {json.dumps(label)} OR name {operator} {json.dumps(label)}'})
    return result
def eid(el):return el.get('element-6066-11e4-a52e-4f735466cecf') or el.get('ELEMENT')
def click_native(label,contains=False):
    found=find_native(label,contains)
    if not found:return False
    cmd('POST','/element/'+eid(found[-1])+'/click',{});time.sleep(1);return True
def tap_ocr(needle,label,exact=False,lowest=False):
    rows=capture(label,True)
    matches=[r for r in rows if (r['text'].replace(' ','')==needle.replace(' ','') if exact else needle.replace(' ','') in r['text'].replace(' ',''))]
    assert matches,{'missing':needle,'ocr':[r['text'] for r in rows]}
    row=max(matches,key=lambda x:x['y']) if lowest else matches[0]
    rect=cmd('GET','/window/rect')
    execute('mobile: tap',[{'x':row['x']*rect['width'],'y':row['y']*rect['height']}]);time.sleep(1)
def page_state():
    webview()
    return execute('return {href:location.href,ua:navigator.userAgent,inner:[innerWidth,innerHeight],canvas:document.querySelector("canvas")?.getBoundingClientRect().toJSON(),status:!!document.getElementById("status"),engine:typeof Engine,standalone:navigator.standalone};')
def close_room():
    global code
    if not code:return
    try:
        tap_ocr('回到房間','cleanup-room')
    except Exception:pass
    try:
        tap_ocr('離開','cleanup-leave')
        tap_ocr('關閉房間','cleanup-close')
        tap_ocr('確認關閉房間','cleanup-confirm')
        capture('room-cleaned',True);code=None
    except Exception as e:report['cleanup_error']=str(e);save()
try:
    caps={'platformName':'iOS','appium:platformVersion':'26.5','appium:automationName':'XCUITest','appium:udid':Path('qa-ios-evidence/udid.txt').read_text().strip(),'appium:bundleId':'com.apple.mobilesafari','appium:showXcodeLog':True,'appium:includeSafariInWebviews':True,'appium:connectHardwareKeyboard':False,'appium:forceSimulatorSoftwareKeyboardPresence':True,'appium:newCommandTimeout':180,'appium:wdaLaunchTimeout':120000,'appium:usePreinstalledWDA':True,'appium:prebuiltWDAPath':Path('qa-ios-evidence/wda-path.txt').read_text().strip(),'appium:noReset':True}
    value=call('POST','/session',{'capabilities':{'alwaysMatch':caps}});session=value['sessionId']
    report['phase']='native-ready';save();capture('native-session-ready')
    report['active_app']=execute('mobile: activeAppInfo');save()
    for name in ['Continue','Start Browsing','Not Now']:
        if click_native(name):capture('onboarding-'+name.replace(' ','-'))
    execute('mobile: deepLink',[{'url':root,'bundleId':'com.apple.mobilesafari'}]);time.sleep(8)
    capture('safari-opened')
    deadline=time.monotonic()+100;state={}
    while time.monotonic()<deadline:
        state=page_state()
        if state.get('canvas') and state.get('engine')=='function' and not state['status']:break
        time.sleep(3)
    check('actual iOS Safari Godot startGame resolved',state.get('canvas') and not state.get('status',True),state)
    report['phase']='game-ready';save();capture('safari-game-ready',True)
    tap_ocr('以訪客身分登入','guest-choice')
    tap_ocr('開始遊戲','menu-start')
    tap_ocr('你的暱稱','nickname-focus',exact=True,lowest=True)
    keyboard=execute('mobile: isKeyboardShown')
    check('real iOS software keyboard shown',keyboard)
    capture('ios-keyboard-before-input')
    active=cmd('GET','/element/active')
    cmd('POST','/element/'+eid(active)+'/value',{'text':'iOS26QA'})
    capture('ios-keyboard-typed',True)
    # Use the actual software keyboard Done control when available.
    if not click_native('Done'):
        rect=cmd('GET','/window/rect');execute('mobile: tap',[{'x':20,'y':rect['height']*0.22}]);time.sleep(1)
    tap_ocr('建立並成為房主','create-room')
    deadline=time.monotonic()+15;rooms=[]
    while time.monotonic()<deadline:
        rooms=json.load(urllib.request.urlopen('https://140-120-53-5.sslip.io/api/rooms',timeout=10))['rooms']
        mine=[r for r in rooms if r.get('host_name')=='iOS26QA']
        if mine:code=mine[0]['code'];break
        time.sleep(1)
    check('native keyboard nickname reaches real WSS room',code is not None,code)
    capture('actual-room-created',True)
    tap_ocr('開始第一回合','start-game')
    for digit in ['1','2','3','4']:tap_ocr(digit,'guess-key-'+digit,exact=True,lowest=True)
    tap_ocr('送出猜測','guess-submit')
    tap_ocr('猜測紀錄','guess-history')
    rows=capture('actual-guess-history',True)
    check('history rendered after actual four-digit submission',any('筆' in r['text'] for r in rows),[r['text'] for r in rows])
    tap_ocr('數字狀態','notes-tab')
    tap_ocr('1位','position-select')
    tap_ocr('設為數字3','position-three')
    capture('actual-note-confirmed',True)
    execute('mobile: pressButton',[{'name':'home'}]);time.sleep(3)
    execute('mobile: activateApp',[{'bundleId':'com.apple.mobilesafari'}]);time.sleep(3)
    capture('actual-background-resume',True)
    check('background return remains at game origin',page_state()['href'].startswith(root))
    close_room()
    native();report['phase']='add-to-home';save()
    if not click_native('Share'):
        found=False
        for name in ['More','Page Menu','More Options']:
            if click_native(name):found=True;break
        capture('safari-share-menu')
        if not click_native('Share'):
            tap_ocr('Share','share-action')
    capture('share-sheet')
    if not click_native('Add to Home Screen',True):
        execute('mobile: swipe',[{'direction':'up'}]);time.sleep(1)
        check('Add to Home Screen action reachable',click_native('Add to Home Screen',True))
    capture('add-home-dialog')
    switches=cmd('POST','/elements',{'using':'class name','value':'XCUIElementTypeSwitch'})
    for switch in switches:
        val=cmd('GET','/element/'+eid(switch)+'/attribute/value')
        if val=='0':cmd('POST','/element/'+eid(switch)+'/click',{})
    check('native Add installs Home Screen app',click_native('Add'))
    execute('mobile: pressButton',[{'name':'home'}]);time.sleep(2)
    capture('springboard-installed')
    check('installed 1A2B icon launches',click_native('1A2B',True))
    time.sleep(6);web=None
    info=execute('mobile: activeAppInfo');report['installed_app_info']=info
    state=page_state()
    check('actual installed app reports standalone',state.get('standalone') is True,state)
    check('installed root launch excludes invitation room','room=' not in state['href'])
    capture('installed-standalone',True)
    native();execute('mobile: pressButton',[{'name':'home'}]);time.sleep(2);check('installed app relaunch',click_native('1A2B',True));time.sleep(3);capture('installed-relaunched')
    report['phase']='complete';report['passed']=True;save();print('IOS26_FUNCTIONAL_ACCEPTANCE_PASSED',flush=True)
except Exception:
    report['error']=traceback.format_exc();report['passed']=False;save()
    if session:
        try:capture('failure-native',True)
        except Exception as e:report['capture_error']=str(e);save()
    raise
finally:
    if session:
        try:native();close_room()
        except Exception:pass
        try:cmd('DELETE','',timeout=15)
        except Exception:pass

