import os,json,time,urllib.request,urllib.error,base64,traceback,subprocess,re
from pathlib import Path
out=Path('qa-ios-evidence/pwa');out.mkdir(parents=True,exist_ok=True)
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
    # A full accessibility snapshot during WebAssembly compilation can block WDA.
    # Screenshots/OCR are the required rendered evidence; native queries stay targeted.
    if ocr:
        rows=json.loads(subprocess.check_output(['./qa-ios/ocr',str(path)],timeout=40))
        out.joinpath(label+'-ocr.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False));return rows
def find_native(label,contains=False):
    native();operator='CONTAINS' if contains else '=='
    result=cmd('POST','/elements',{'using':'-ios predicate string','value':f'(label {operator} {json.dumps(label)} OR name {operator} {json.dumps(label)}) AND visible == true'})
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
    return execute('const s=document.getElementById("status");return {href:location.href,ua:navigator.userAgent,inner:[innerWidth,innerHeight],ua:navigator.userAgent,buffer:[document.querySelector("canvas")?.width,document.querySelector("canvas")?.height],canvas:document.querySelector("canvas")?.getBoundingClientRect().toJSON(),status:!!s && !s.hidden && getComputedStyle(s).display!=="none" && getComputedStyle(s).visibility!=="hidden",engine:typeof Engine,standalone:navigator.standalone};')
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
def dismiss_known_engine_alert(label):
    rows=capture(label,True)
    observed=any('WebGLcontextlost' in r['text'].replace(' ','') for r in rows)
    report.setdefault('engine_alert_observations',[]).append({'label':label,'observed':observed});save()
    if observed:check(label+' native alert dismissed for OS navigation',click_native('Close'))
    return observed

def home_icon(label):
    native();execute('mobile: pressButton',[{'name':'home'}]);time.sleep(2)
    for page in range(3):
        capture(label+'-page-'+str(page))
        found=cmd('POST','/elements',{'using':'-ios predicate string','value':'(label == "1A2B" OR name == "1A2B") AND visible == true'})
        if found:
            cmd('POST','/element/'+eid(found[-1])+'/click',{});time.sleep(3);return True
        execute('mobile: swipe',[{'direction':'left'}]);time.sleep(1)
    return False

def standalone_state():
    global web,want_standalone
    web=None;want_standalone=True;webview()
    return execute('return {href:location.href,standalone:navigator.standalone===true,displayStandalone:matchMedia("(display-mode: standalone)").matches,title:document.title};')

try:
    caps={'platformName':'iOS','browserName':'Safari','appium:platformVersion':os.getenv('IOS_VERSION','26.5'),'appium:safariInitialUrl':'about:blank','appium:webviewConnectTimeout':20000,'appium:automationName':'XCUITest','appium:udid':Path('qa-ios-evidence/udid.txt').read_text().strip(),'appium:showXcodeLog':True,'appium:includeSafariInWebviews':True,'appium:additionalWebviewBundleIds':['*'],'appium:connectHardwareKeyboard':False,'appium:forceSimulatorSoftwareKeyboardPresence':True,'appium:newCommandTimeout':180,'appium:wdaLaunchTimeout':120000,'appium:usePreinstalledWDA':True,'appium:prebuiltWDAPath':Path('qa-ios-evidence/wda-path.txt').read_text().strip(),'appium:noReset':False}
    caps['appium:webviewConnectTimeout']=60000
    try:
        value=call('POST','/session',{'capabilities':{'alwaysMatch':caps}})
    except RuntimeError as e:
        if 'did not return any connected web applications' not in str(e):raise
        # One bounded recovery on this already booted device, never restart until green.
        report['safari_startup_failure']=str(e);report['native_session_fallback']=True;save()
        caps.pop('browserName');caps.pop('appium:safariInitialUrl')
        caps.update({'appium:bundleId':'com.apple.mobilesafari','appium:autoWebview':False,'appium:noReset':True})
        value=call('POST','/session',{'capabilities':{'alwaysMatch':caps}})
    session=value['sessionId']
    report['phase']='native-ready';save();capture('native-session-ready')
    report['active_app']=execute('mobile: activeAppInfo');save()
    for name in ['Continue','Start Browsing','Not Now']:
        if click_native(name):capture('onboarding-'+name.replace(' ','-'))
    click_native('xmark.circle.fill')
    if report.get('native_session_fallback'):
        execute('mobile: deepLink',[{'url':'about:blank','bundleId':'com.apple.mobilesafari'}]);time.sleep(3);capture('native-blank-opened',True)
    report['purpose']='Independent OS Home Screen installation, separate from blocked Godot rendering';save()
    webview(allow_blank=True);cmd('POST','/url',{'url':root+'?room=INVALID'},timeout=90);web=None
    native();click_native('xmark.circle.fill');time.sleep(45)
    dismiss_known_engine_alert('formal-safari-rendering-status')
    native()
    if not click_native('Share'):
        check('Safari page menu opens',click_native('More') or click_native('MoreMenuButton'))
        capture('formal-safari-page-menu',True)
        check('Safari native Share opens',click_native('Share') or click_native('Share',True))
    capture('formal-share-sheet',True)
    reached=False
    for attempt in range(4):
        if click_native('Add to Home Screen',True):reached=True;break
        execute('mobile: swipe',[{'direction':'up'}]);time.sleep(1);capture('share-actions-scroll-'+str(attempt),True)
    check('actual Add to Home Screen action',reached)
    capture('formal-add-home-dialog',True)
    switches=cmd('POST','/elements',{'using':'-ios predicate string','value':'type == "XCUIElementTypeSwitch" AND (label CONTAINS "Open as Web App" OR name CONTAINS "Open as Web App")'})
    check('actual Open as Web App setting identified',len(switches)==1)
    switch=switches[0];value=cmd('GET','/element/'+eid(switch)+'/attribute/value')
    if value=='0':cmd('POST','/element/'+eid(switch)+'/click',{})
    check('Open as Web App is enabled',cmd('GET','/element/'+eid(switch)+'/attribute/value')=='1')
    check('native Add action installs app',click_native('Add'))
    check('actual installed Home Screen icon launches',home_icon('installed-home-icon'))
    time.sleep(30);dismiss_known_engine_alert('standalone-rendering-status')
    info=execute('mobile: activeAppInfo');report['installed_app_info']=info;save()
    check('actual installed app foreground info',str(info.get('bundleId','')).startswith('com.apple.webapp') and info.get('pid',0)>0,info)
    state=standalone_state()
    check('actual standalone context at exact public root',state['standalone'] and state['href']==root,state)
    check('invitation query excluded from installed start URL','room=' not in state['href'],state)
    capture('installed-real-standalone',True)
    native();before=execute('mobile: queryAppState',[{'bundleId':info['bundleId']}]);terminated=execute('mobile: terminateApp',[{'bundleId':info['bundleId']}]);after=execute('mobile: queryAppState',[{'bundleId':info['bundleId']}])
    check('actual installed app process terminated',before==4 and terminated is True and after==1,{'before':before,'terminated':terminated,'after':after})
    check('terminated app launched from actual icon',home_icon('terminated-home-icon'))
    time.sleep(30);dismiss_known_engine_alert('relaunched-rendering-status')
    reopened=execute('mobile: activeAppInfo');reopened_state=execute('mobile: queryAppState',[{'bundleId':info['bundleId']}]);report['reopened_app_info']=reopened;report['reopened_app_state']=reopened_state;save()
    check('new installed app foreground process',reopened_state==4 and reopened.get('bundleId')==info['bundleId'] and reopened.get('pid',0)>0 and reopened.get('pid')!=info.get('pid'),reopened)
    state=standalone_state();check('terminated app returns to true standalone root',state['standalone'] and state['href']==root,state)
    capture('installed-real-process-relaunch',True)
    report['phase']='pwa-os-complete';report['pwa_os_passed']=all(c['passed'] for c in report['checks']);report['game_ready']=False;save()
    assert report['pwa_os_passed']
    print('IOS_PWA_OS_ACCEPTANCE_PASSED_GAME_RENDERING_SEPARATE',flush=True)
except Exception:
    report['error']=traceback.format_exc();report['pwa_os_passed']=False;report['game_ready']=False;save()
    if session:
        try:capture('pwa-os-failure',True)
        except Exception as e:report['capture_error']=str(e);save()
    raise
finally:
    if session:
        try:cmd('DELETE','',timeout=15)
        except Exception:pass

