import {createRequire} from 'node:module';
import {resolve,dirname} from 'node:path';
import {existsSync} from 'node:fs';
let playwright,dependencyRequire;try{dependencyRequire=createRequire(import.meta.url);playwright=dependencyRequire('playwright');}catch{try{dependencyRequire=createRequire(process.env.RADAR_BROWSER_PACKAGE||resolve('work/platform-browser/package.json'));playwright=dependencyRequire('playwright');}catch{}}
let input='';for await(const chunk of process.stdin)input+=chunk;
const request=JSON.parse(input||'{}');
const executable=process.env.RADAR_BROWSER_EXECUTABLE||playwright?.chromium.executablePath();
if(request.operation==='status'){
 console.log(JSON.stringify({available:!!executable&&existsSync(executable),library:!!playwright,executable,cli:playwright?resolve(dirname(dependencyRequire.resolve('playwright/package.json')),'cli.js'):undefined}));
}else{
 const url=new URL(request.url);if(url.protocol!=='https:'||url.hostname!=='mp.weixin.qq.com'||url.username||url.password)throw new Error('浏览器仅接受公开公众号文章HTTPS链接');
 if(!playwright)throw new Error('平台浏览器未安装，运行python collector/setup_platforms.py');
 const browser=await playwright.chromium.launch({headless:true,...(process.env.RADAR_BROWSER_EXECUTABLE?{executablePath:executable}:{})});
 try{
  const page=await browser.newPage();await page.route('**/*',route=>['image','media','font'].includes(route.request().resourceType())?route.abort():route.continue());
  await page.goto(url.href,{waitUntil:'domcontentloaded',timeout:25000});
  await page.locator('#js_content').waitFor({timeout:8000}).catch(()=>{});
  const result=await page.evaluate(()=>({url:location.href,title:document.querySelector('#activity-name')?.textContent?.trim()||document.title,account:document.querySelector('#js_name')?.textContent?.trim()||'',publishedAt:document.querySelector('#publish_time')?.textContent?.trim()||'',body:document.querySelector('#js_content')?.textContent?.trim()||'',html:document.documentElement.outerHTML.slice(0,1500000)}));
  if(result.body.length<50)throw new Error('公众号正文不可读取，可能为验证页、限流或已删除文章');
  console.log(JSON.stringify(result));
 }finally{await browser.close();}
}
