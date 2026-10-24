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
    # A full accessibility snapshot during WebAssembly compilation can block WDA.
    # Screenshots/OCR are the required rendered evidence; native queries stay targeted.
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
    webview(allow_blank=True)
    control=execute('const c=document.createElement("canvas");c.width=256;c.height=256;document.body.append(c);const gl=c.getContext("webgl2");if(!gl)return {supported:false};gl.clearColor(0,1,0,1);gl.clear(gl.COLOR_BUFFER_BIT);const p=new Uint8Array(4);gl.readPixels(0,0,1,1,gl.RGBA,gl.UNSIGNED_BYTE,p);return {supported:true,lost:gl.isContextLost(),pixel:Array.from(p),renderer:gl.getParameter(gl.RENDERER),glError:gl.getError()};')
    capture('webgl2-positive-control',True)
    check('plain WebGL2 positive control on actual simulator',control.get('supported') and not control.get('lost') and control.get('pixel')==[0,255,0,255],control)
    root='http://127.0.0.1:8765/'
    report['diagnostics']=[];save()
    for preserve in [1,0]:
        label='shader-fbo-preserve-'+str(preserve)
        native();execute('mobile: terminateApp',[{'bundleId':'com.apple.mobilesafari'}]);time.sleep(3)
        execute('mobile: deepLink',[{'url':root+'gl-control.html?preserve='+str(preserve),'bundleId':'com.apple.mobilesafari'}]);web=None
        time.sleep(5);capture(label+'-early',True)
        time.sleep(35);capture(label+'-final',True)
        webview();state=execute('return {result:window.glqa||null,ua:navigator.userAgent,url:location.href};')
        result=state.get('result') or {}
        report['diagnostics'].append({'case':label,'state':state});save()
        record(label+' actual shader/FBO/draw/blit/multiframe rendering',result.get('linked') and result.get('complete') and result.get('frames',0)>=30 and not result.get('events') and not result.get('glErrors') and result.get('pixelFailures')==0,state)
    for pack,size in [('minimal-no-msdf','full')]:
        label=pack+'-'+size
        try:
            print('IOS_DIAGNOSTIC_START',label,flush=True)
            web=None
            native();execute('mobile: terminateApp',[{'bundleId':'com.apple.mobilesafari'}]);time.sleep(3)
            execute('mobile: deepLink',[{'url':root+'diagnostic.html?pack='+pack+'&size='+size,'bundleId':'com.apple.mobilesafari'}]);web=None
            time.sleep(12)
            for sample in range(3):
                rows=capture(label+'-'+str(sample),True)
                webview()
                state=execute('return {qa:window.qa||null,url:location.href,ua:navigator.userAgent,buffer:[document.querySelector("canvas")?.width,document.querySelector("canvas")?.height],canvas:document.querySelector("canvas")?.getBoundingClientRect().toJSON()};')
                report['diagnostics'].append({'case':label,'sample':sample,'state':state,'ocr':[r['text'] for r in rows]});save()
                if state.get('qa',{}).get('events') or state.get('qa',{}).get('alerts'):break
                if state.get('qa',{}).get('resolved'):
                    if pack.startswith('minimal'):
                        native();tap_ocr('Native clicks: 0',label+'-button')
                        rows=capture(label+'-clicked',True)
                        record(label+' actual native click',any('Nativeclicks:1' in r['text'].replace(' ','') for r in rows),[r['text'] for r in rows])
                    if pack.startswith('minimal') or sample>=1:break
                time.sleep(15)
            native()
        except Exception:
            report['diagnostics'].append({'case':label,'error':traceback.format_exc()});save()
            print('IOS_DIAGNOSTIC_CASE_FAILED',label,flush=True)
    report['phase']='diagnostic-complete';save()
    print('IOS_DIAGNOSTIC_COMPLETED',flush=True)
except Exception:
    report['error']=traceback.format_exc();save()
    if session:
        try:capture('diagnostic-failure',True)
        except Exception as e:report['capture_error']=str(e);save()
    raise
finally:
    if session:
        try:cmd('DELETE','',timeout=15)
        except Exception:pass

