import os,json,time,urllib.request,urllib.error,base64,traceback,subprocess,re
from pathlib import Path
out=Path('qa-ios-evidence');out.mkdir(exist_ok=True)
base='http://127.0.0.1:4723';session=None;web=None;code=None;want_standalone=False
root='https://funji713.github.io/1a2b-invite/'
report={'started':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'run':os.getenv('GITHUB_RUN_ID'),'checks':[],'phase':'startup'}
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
def webview(allow_blank=False):
    global web
    if web:cmd('POST','/context',{'name':web});return
    for attempt in range(8):
        contexts=cmd('GET','/contexts');out.joinpath('contexts.json').write_text(json.dumps(contexts,indent=2))
        candidates=[x for x in contexts if x!='NATIVE_APP']
        for candidate in candidates:
            try:
                cmd('POST','/context',{'name':candidate})
                href=execute('return location.href')
                eligible=href.startswith(root) or (allow_blank and href=='about:blank')
                if eligible and (not want_standalone or execute('return navigator.standalone===true')):web=candidate;return
            except Exception:pass
        native()
        time.sleep(4)
    raise AssertionError('No actual Safari web context')
def check(name,condition,details=None):
    record(name,condition,details)
    assert condition,name
def record(name,condition,details=None):
    report['checks'].append({'name':name,'passed':bool(condition),'details':details});save()
    print('IOS_CHECK',name,bool(condition),flush=True)
def capture(label,ocr=False):
    report['last_capture']=label;save();print('IOS_CAPTURE',label,flush=True)
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
    norm=lambda text:text.replace(' ','').replace('…','...')
    matches=[r for r in rows if (norm(r['text'])==norm(needle) if exact else norm(needle) in norm(r['text']))]
    assert matches,{'missing':needle,'ocr':[r['text'] for r in rows]}
    row=max(matches,key=lambda x:x['y']) if lowest else matches[0]
    rect=cmd('GET','/window/rect')
    execute('mobile: tap',[{'x':row['x']*rect['width'],'y':row['y']*rect['height']}]);time.sleep(1)
def focus_nickname(label):
    rows=capture(label,True)
    for value in ['你的暱稱','iOS26QA','StandaloneiOSQA']:
        if any(r['text'].replace(' ','')==value for r in rows):
            tap_ocr(value,label+'-field',exact=True);return
    raise AssertionError({'nickname_field_not_found':[r['text'] for r in rows]})
def page_state():
    webview()
    return execute('const s=document.getElementById("status");return {href:location.href,ua:navigator.userAgent,inner:[innerWidth,innerHeight],canvas:document.querySelector("canvas")?.getBoundingClientRect().toJSON(),status:!!s && !s.hidden && getComputedStyle(s).display!=="none" && getComputedStyle(s).visibility!=="hidden",engine:typeof Engine,standalone:navigator.standalone};')
def layout_check(name):
    webview()
    state=execute('const r=document.querySelector("canvas").getBoundingClientRect(),v=visualViewport;return {rect:r.toJSON(),viewport:{width:v.width,height:v.height,offsetTop:v.offsetTop,offsetLeft:v.offsetLeft,scale:v.scale},innerHeight:innerHeight};')
    v=state['viewport'];r=state['rect'];top=max(0,min(v['offsetTop'],state['innerHeight']-v['height']))
    check(name,abs(r['height']-v['height'])<2 and abs(r['width']-v['width'])<2 and abs(r['top']-top)<2,state)
    native()
def close_room():
    global code
    if not code:return
    try:
        tap_ocr('回到房間','cleanup-room')
    except Exception:pass
    try:
        tap_ocr('離開','cleanup-leave')
        tap_ocr('關閉房間…','cleanup-close',exact=True)
        tap_ocr('確認關閉房間','cleanup-confirm',exact=True)
        capture('room-cleaned',True);code=None
    except Exception as e:report['cleanup_error']=str(e);save()
try:
    caps={'platformName':'iOS','browserName':'Safari','appium:platformVersion':'26.5','appium:safariInitialUrl':'about:blank','appium:webviewConnectTimeout':20000,'appium:automationName':'XCUITest','appium:udid':Path('qa-ios-evidence/udid.txt').read_text().strip(),'appium:showXcodeLog':True,'appium:includeSafariInWebviews':True,'appium:connectHardwareKeyboard':False,'appium:forceSimulatorSoftwareKeyboardPresence':True,'appium:newCommandTimeout':180,'appium:wdaLaunchTimeout':120000,'appium:usePreinstalledWDA':True,'appium:prebuiltWDAPath':Path('qa-ios-evidence/wda-path.txt').read_text().strip(),'appium:noReset':False}
    value=call('POST','/session',{'capabilities':{'alwaysMatch':caps}});session=value['sessionId']
    report['phase']='native-ready';save();capture('native-session-ready')
    report['active_app']=execute('mobile: activeAppInfo');save()
    for name in ['Continue','Start Browsing','Not Now']:
        if click_native(name):capture('onboarding-'+name.replace(' ','-'))
    click_native('xmark.circle.fill')
    webview(allow_blank=True)
    control=execute('const c=document.createElement("canvas");c.width=256;c.height=256;document.body.append(c);const gl=c.getContext("webgl2");if(!gl)return {supported:false};gl.clearColor(0,1,0,1);gl.clear(gl.COLOR_BUFFER_BIT);const p=new Uint8Array(4);gl.readPixels(0,0,1,1,gl.RGBA,gl.UNSIGNED_BYTE,p);return {supported:true,lost:gl.isContextLost(),pixel:Array.from(p),renderer:gl.getParameter(gl.RENDERER),glError:gl.getError()};')
    capture('webgl2-positive-control',True)
    check('plain WebGL2 positive control on actual simulator',control.get('supported') and not control.get('lost') and control.get('pixel')==[0,255,0,255],control)
    webview(allow_blank=True);cmd('POST','/url',{'url':root},timeout=90);web=None
    native();click_native('xmark.circle.fill');time.sleep(8)
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
    focus_nickname('nickname-focus')
    keyboard=execute('mobile: isKeyboardShown')
    check('real iOS software keyboard shown',keyboard)
    capture('ios-keyboard-before-input')
    layout_check('native keyboard visible canvas layout')
    active=cmd('GET','/element/active')
    cmd('POST','/element/'+eid(active)+'/value',{'text':'iOS26QA'})
    capture('ios-keyboard-typed',True)
    # Use the actual software keyboard Done control when available.
    if not click_native('Done'):
        rect=cmd('GET','/window/rect');execute('mobile: tap',[{'x':20,'y':rect['height']*0.22}]);time.sleep(1)
    check('native keyboard dismissed',not execute('mobile: isKeyboardShown'))
    layout_check('native keyboard hidden canvas layout')
    tap_ocr('建立並成為房主','create-room')
    deadline=time.monotonic()+15;rooms=[]
    while time.monotonic()<deadline:
        rooms=json.load(urllib.request.urlopen('https://140-120-53-5.sslip.io/api/rooms',timeout=10))['rooms']
        mine=[r for r in rooms if r.get('host_name')=='iOS26QA']
        if mine:code=mine[0]['code'];break
        time.sleep(1)
    check('native keyboard nickname reaches real WSS room',code is not None,code)
    capture('actual-room-created',True)
    try:
        tap_ocr('複製連結','native-copy-invite',exact=True)
        copied=base64.b64decode(execute('mobile: getClipboard',[{'contentType':'plaintext'}])).decode('utf-8')
        record('actual iOS pasteboard contains own copied invitation',copied==root+'?room='+code,{'matches_expected':copied==root+'?room='+code})
    except Exception:
        record('actual iOS pasteboard contains own copied invitation',False,traceback.format_exc())
        capture('native-clipboard-failure')
    # The app's chat drawer has a visible text toggle; find it from actual pixels.
    tap_ocr('<<','chat-open')
    tap_ocr('輸入訊息','chat-input-focus')
    check('real iOS chat software keyboard shown',execute('mobile: isKeyboardShown'))
    active=cmd('GET','/element/active')
    cmd('POST','/element/'+eid(active)+'/value',{'text':'原生中文聊天驗證'})
    capture('ios-chinese-chat-keyboard',True)
    if not click_native('Done'):
        rect=cmd('GET','/window/rect');execute('mobile: tap',[{'x':rect['width']*0.35,'y':rect['height']*0.25}]);time.sleep(1)
    tap_ocr('傳送','chat-send')
    rows=capture('ios-chinese-chat-sent',True)
    check('Chinese chat visible after send',any('原生中文聊天驗證' in r['text'].replace(' ','') for r in rows),[r['text'] for r in rows])
    tap_ocr('>>','chat-close')
    tap_ocr('開始第一回合','start-game')
    for digit in ['1','2','3','4']:tap_ocr(digit,'guess-key-'+digit,exact=True,lowest=True)
    tap_ocr('送出猜測','guess-submit')
    tap_ocr('猜測紀錄','guess-history')
    rows=capture('actual-guess-history',True)
    text=' '.join(r['text'] for r in rows)
    check('positive history count after actual four-digit submission',bool(re.search(r'[1-9][0-9]*\s*筆',text)),text)
    check('actual guess digits and score rendered',all(d in text for d in '1234') and bool(re.search(r'[0-4]\s*A',text,re.I)),text)
    tap_ocr('數字狀態','notes-tab')
    tap_ocr('1位','position-select')
    tap_ocr('設為數字3','position-three')
    capture('actual-note-confirmed',True)
    cmd('POST','/orientation',{'orientation':'LANDSCAPE'});time.sleep(2);capture('actual-landscape-notes',True);layout_check('actual iOS landscape canvas bounds')
    cmd('POST','/orientation',{'orientation':'PORTRAIT'});time.sleep(2);capture('actual-portrait-restored',True);layout_check('actual iOS portrait canvas bounds')
    native();execute('mobile: pinch',[{'scale':1.5,'velocity':1.0}]);time.sleep(1)
    webview();zoom=execute('return {scale:visualViewport.scale,x:visualViewport.offsetLeft,y:visualViewport.offsetTop};')
    check('actual native iOS pinch zooms browser',zoom['scale']>1.1,zoom);capture('actual-native-pinch')
    rect=cmd('GET','/window/rect');execute('mobile: dragFromToForDuration',[{'duration':0.5,'fromX':rect['width']*0.65,'fromY':rect['height']*0.55,'toX':rect['width']*0.4,'toY':rect['height']*0.4}]);time.sleep(1);capture('actual-zoomed-pan')
    native();execute('mobile: pinch',[{'scale':0.5,'velocity':-1.0}]);time.sleep(1);capture('actual-pinch-restored',True)
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
    switches=cmd('POST','/elements',{'using':'-ios predicate string','value':'type == "XCUIElementTypeSwitch" AND (label CONTAINS "Open as Web App" OR name CONTAINS "Open as Web App")'})
    check('Open as Web App control identified',len(switches)==1)
    for switch in switches:
        val=cmd('GET','/element/'+eid(switch)+'/attribute/value')
        if val=='0':cmd('POST','/element/'+eid(switch)+'/click',{})
    check('native Add installs Home Screen app',click_native('Add'))
    execute('mobile: pressButton',[{'name':'home'}]);time.sleep(2)
    capture('springboard-installed')
    check('installed 1A2B icon launches',click_native('1A2B',True))
    time.sleep(6);web=None;want_standalone=True
    info=execute('mobile: activeAppInfo');report['installed_app_info']=info
    check('installed app uses a separate native web app',info.get('bundleId')!='com.apple.mobilesafari',info)
    deadline=time.monotonic()+80;state={}
    while time.monotonic()<deadline:
        state=page_state()
        if state.get('canvas') and not state.get('status',True):break
        time.sleep(2)
    check('installed Godot startup resolved',state.get('canvas') and not state.get('status',True),state)
    check('actual installed app reports standalone',state.get('standalone') is True,state)
    check('installed root launch excludes invitation room','room=' not in state['href'])
    capture('installed-standalone',True)
    rows=capture('standalone-entry',True)
    if any('以訪客身分登入' in r['text'].replace(' ','') for r in rows):tap_ocr('以訪客身分登入','standalone-guest')
    tap_ocr('開始遊戲','standalone-start')
    focus_nickname('standalone-nickname')
    check('standalone native keyboard visible',execute('mobile: isKeyboardShown'))
    active=cmd('GET','/element/active');cmd('POST','/element/'+eid(active)+'/clear',{});cmd('POST','/element/'+eid(active)+'/value',{'text':'StandaloneiOSQA'})
    capture('standalone-native-input',True)
    native();execute('mobile: pressButton',[{'name':'home'}]);time.sleep(2);check('installed app relaunch',click_native('1A2B',True));time.sleep(3);capture('installed-relaunched')
    report['phase']='complete';report['passed']=all(c['passed'] for c in report['checks']);save()
    assert report['passed'],'One or more independent checks failed; retained results are not an overall pass'
    print('IOS26_FUNCTIONAL_ACCEPTANCE_PASSED',flush=True)
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

