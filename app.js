"use strict";
(() => {
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const toast = $("#toast");
let toastTimer, sb = null, user = null, username = null, isAdmin = false, authMode = "signin";
let posts = [], photos = [];
const cfg = window.STONELAND_CONFIG || {};
const configured = Boolean(cfg.supabaseUrl && /^https:\/\/[a-z0-9-]+\.supabase\.co\/?$/.test(cfg.supabaseUrl) && cfg.supabaseKey && (cfg.supabaseKey.startsWith("sb_publishable_") || cfg.supabaseKey.split(".").length === 3));
const emailFor = name => name.toLowerCase() + "@stoneland.invalid";
const displayName = n => n === "sewapro" ? "SeWapro" : n;
const shortDate = date => new Date(date).toLocaleDateString("uk-UA",{day:"numeric",month:"long",year:"numeric"});
const el = (tag,className,text) => { const node=document.createElement(tag); if(className)node.className=className; if(text!==undefined)node.textContent=text; return node; };
function notify(text){toast.textContent=text;toast.classList.add("shown");clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.remove("shown"),4400)}
function report(id,text,error=false){const n=$(id);if(!n)return;n.textContent=text;n.classList.toggle("error",error)}
function go(name){if(!["home","news","gallery","community","account","admin"].includes(name))name="home";if(name==="admin"&&!isAdmin){name="account";notify("Адмінпанель доступна лише адміністратору.");}
 $$(".page").forEach(p=>p.classList.toggle("hidden",p.dataset.page!==name));
 $$("[data-link]").forEach(a=>{const active=a.dataset.link===name;a.classList.toggle("active",active);if(active)a.setAttribute("aria-current","page");else a.removeAttribute("aria-current")});
 $("#nav").classList.remove("open");$("#menu-button").setAttribute("aria-expanded","false");$("#menu-button").setAttribute("aria-label","Відкрити меню");
 if(location.hash!=="#"+name)history.replaceState(null,"","#"+name);
 document.title=(name==="home"?"StoneLand II":({news:"Новини",gallery:"Галерея",community:"Спільнота",account:"Кабінет",admin:"Адмінпанель"}[name]+" — StoneLand II"));
 window.scrollTo({top:0,behavior:"instant"});
}
window.addEventListener("hashchange",()=>go(decodeURIComponent(location.hash.slice(1))));
$$("[data-go]").forEach(b=>b.addEventListener("click",()=>go(b.dataset.go)));
$("#account-button").addEventListener("click",()=>go("account"));
$("#menu-button").addEventListener("click",()=>{const menu=$("#nav");const open=menu.classList.toggle("open");$("#menu-button").setAttribute("aria-expanded",String(open));$("#menu-button").setAttribute("aria-label",open?"Закрити меню":"Відкрити меню")});
document.addEventListener("keydown",e=>{if(e.key==="Escape"){$("#nav").classList.remove("open");$("#menu-button").setAttribute("aria-expanded","false")}});
$("#year").textContent=String(new Date().getFullYear());
function authTab(mode){authMode=mode;$$("[data-auth-tab]").forEach(btn=>{const active=btn.dataset.authTab===mode;btn.classList.toggle("selected",active);btn.setAttribute("aria-selected",String(active))});const reg=mode==="signup";$("#auth-title").textContent=reg?"Новий гравець":"Повернення у світ";$("#auth-subtitle").textContent=reg?"Створи акаунт без пошти.":"Введи свій логін і пароль.";$("#auth-submit").firstChild.textContent=reg?"Зареєструватись ":"Увійти ";$("#confirm-label").classList.toggle("hidden",!reg);$("#confirm-password").classList.toggle("hidden",!reg);$("#confirm-password").required=reg;$("#password").autocomplete=reg?"new-password":"current-password";report("#auth-message","")}
$$("[data-auth-tab]").forEach(b=>b.addEventListener("click",()=>authTab(b.dataset.authTab)));
$("#show-password").addEventListener("click",()=>{const p=$("#password");p.type=p.type==="password"?"text":"password";$("#show-password").setAttribute("aria-label",p.type==="text"?"Сховати пароль":"Показати пароль")});
function renderAccount(){const signed=Boolean(user);$("#logged-out").classList.toggle("hidden",signed);$("#logged-in").classList.toggle("hidden",!signed);$("#account-label").textContent=signed?displayName(username||"Гравець"):"Увійти";$$(".admin-nav").forEach(n=>n.classList.toggle("hidden",!isAdmin));$("#open-admin").classList.toggle("hidden",!isAdmin);$("#admin-guard").classList.toggle("hidden",isAdmin);$("#admin-content").classList.toggle("hidden",!isAdmin);if(signed){$("#profile-username").textContent=displayName(username||"Гравець");$("#profile-avatar").textContent=(username||"S").charAt(0).toUpperCase();$("#profile-role").textContent=isAdmin?"Адміністратор":"Гравець";}}
$("#logout").addEventListener("click",async()=>{if(sb){const {error}=await sb.auth.signOut();if(error){notify("Не вдалося вийти. Спробуй ще раз.");return;}}user=null;username=null;isAdmin=false;renderAccount();go("home");notify("Ти вийшов з акаунта.")});
$("#open-admin").addEventListener("click",()=>go("admin"));
async function refreshAccount(){if(!sb)return;const {data:{user:u},error}=await sb.auth.getUser();user=error?null:u;isAdmin=false;username=null;if(user){const [p,a]=await Promise.all([sb.from("sl2_profiles").select("username").eq("id",user.id).maybeSingle(),sb.from("sl2_admins").select("user_id").eq("user_id",user.id).maybeSingle()]);username=p.data?.username||user.email?.split("@")[0]||"Гравець";isAdmin=Boolean(a.data?.user_id);}renderAccount();if(!isAdmin&&location.hash==="#admin")go("account")}
$("#auth-form").addEventListener("submit",async(e)=>{e.preventDefault();if(!sb){report("#auth-message","Підключення до Supabase ще не завершено. Адміністратор має вказати параметри проєкту.",true);return;}
 const form=e.currentTarget, handle=form.elements.username.value.trim(),password=form.elements.password.value;
 if(!/^[A-Za-z][A-Za-z0-9_]{2,19}$/.test(handle)){report("#auth-message","Логін: 3–20 символів, лише латиниця, цифри й підкреслення.",true);return;}
 if(authMode==="signup" && handle.toLowerCase()==="sewapro"){report("#auth-message","Цей логін зарезервовано.",true);return;}
 if(authMode==="signup" && password!==form.elements["confirm-password"].value){report("#auth-message","Паролі не збігаються.",true);return;}
 const btn=$("#auth-submit");btn.disabled=true;report("#auth-message","Зачекай, перевіряємо дані...");
 try {const response=authMode==="signup"?await sb.auth.signUp({email:emailFor(handle),password}):await sb.auth.signInWithPassword({email:emailFor(handle),password});
 if(response.error)throw response.error;
 if(!response.data.session){report("#auth-message","Підтвердження пошти увімкнене в Supabase. Вимкни Confirm email у налаштуваннях Authentication.",true);return;}
 await refreshAccount();form.reset();report("#auth-message","");notify(authMode==="signup"?"Акаунт створено. Вітаємо у StoneLand II!":"Вхід виконано!");
 }catch(err){const msg=String(err?.message||"");report("#auth-message",/already registered/i.test(msg)?"Цей логін уже зайнятий.":/invalid login credentials/i.test(msg)?"Неправильний логін або пароль.":/rate limit|too many/i.test(msg)?"Забагато спроб. Спробуй пізніше.":"Не вдалося виконати дію. Перевір дані та підключення.",true)}finally{btn.disabled=false}
});
function renderPosts(){const list=$("#news-list"),manage=$("#manage-posts");list.replaceChildren();manage.replaceChildren();
if(!posts.length){const empty=el("div","empty");empty.append(el("span","","▦"),el("h3","","Новин поки немає"),el("p","","Слідкуй за оновленнями StoneLand II."));list.append(empty);}
for(const post of posts){const article=el("article","news-card"),meta=el("span","news-meta","▦ / НОВИНИ СЕРВЕРА"),title=el("h2","",post.title),desc=el("p","",post.body),bottom=el("div","news-bottom",shortDate(post.created_at));article.append(meta,title,desc,bottom);list.append(article);
if(isAdmin){const row=el("div","manage-row"),name=el("b","",post.title),del=el("button","delete-btn","Видалити");del.type="button";del.addEventListener("click",()=>deleteItem("post",post.id,post.title));row.append(name,del);manage.append(row);}}
if(!posts.length)manage.append(el("p","manage-empty","Немає публікацій."));}
function renderPhotos(){const list=$("#gallery-list"),manage=$("#manage-photos");list.replaceChildren();manage.replaceChildren();
if(!photos.length){const empty=el("div","empty");empty.append(el("span","","▧"),el("h3","","Фото поки немає"),el("p","","Тут з'являться справжні знімки з Minecraft."));list.append(empty);}
for(const photo of photos){const figure=el("article","photo-card"),img=document.createElement("img"),title=el("h3","",photo.title);img.loading="lazy";img.alt=photo.title;img.src=sb.storage.from("sl2-gallery").getPublicUrl(photo.path).data.publicUrl;figure.append(img,title);list.append(figure);
if(isAdmin){const row=el("div","manage-row"),name=el("b","",photo.title),del=el("button","delete-btn","Видалити");del.type="button";del.addEventListener("click",()=>deleteItem("photo",photo.id,photo.title));row.append(name,del);manage.append(row);}}
if(!photos.length)manage.append(el("p","manage-empty","Фото поки немає."));}
function renderMembers(members){const box=$("#member-list");box.replaceChildren();$("#member-count").textContent=members.length+" учасників зареєстровано";if(!members.length){box.append(el("p","manage-empty","Поки немає зареєстрованих гравців."));return;}members.forEach(m=>{const card=el("article","member"),avatar=el("div","pixel-avatar",m.username.charAt(0).toUpperCase());card.append(avatar,el("b","",displayName(m.username)),el("small","","ГРАВЕЦЬ"));box.append(card)})}
async function loadData(){if(!sb){$("#member-count").textContent="База даних ще не підключена";$("#member-list").append(el("p","manage-empty","Після підключення Supabase тут з'являться гравці."));return;}
 const [p,g,m]=await Promise.all([sb.from("sl2_posts").select("id,title,body,created_at").order("created_at",{ascending:false}).limit(100),sb.from("sl2_photos").select("id,title,path,created_at").order("created_at",{ascending:false}).limit(100),sb.from("sl2_profiles").select("username,created_at").order("created_at",{ascending:false}).limit(100)]);
 posts=p.data||[];photos=g.data||[];renderPosts();renderPhotos();renderMembers(m.data||[]);
 if(p.error||g.error||m.error)notify("Не вдалося завантажити частину даних. Перевір таблиці та RLS у Supabase.");
}
async function deleteItem(type,id,title){if(!isAdmin||!confirm("Видалити «"+title+"»?"))return;
 const table=type==="post"?"sl2_posts":"sl2_photos";const {error}=await sb.from(table).delete().eq("id",id);if(error){notify("Не вдалося видалити запис.");return;}
 if(type==="photo"){const photo=photos.find(p=>p.id===id);if(photo){const {error:storageError}=await sb.storage.from("sl2-gallery").remove([photo.path]);if(storageError)notify("Запис видалено, але файл у Storage залишився.");}}
 notify("Видалено.");await loadData();
}
$$("[data-admin-tab]").forEach(btn=>btn.addEventListener("click",()=>{$$("[data-admin-tab]").forEach(b=>b.classList.toggle("selected",b===btn));$$("[data-admin-panel]").forEach(p=>p.classList.toggle("hidden",p.dataset.adminPanel!==btn.dataset.adminTab))}));
$("#news-form").addEventListener("submit",async(e)=>{e.preventDefault();if(!sb||!isAdmin)return;const form=e.currentTarget,title=form.elements.title.value.trim(),body=form.elements.body.value.trim();if(!title||!body)return;const btn=form.querySelector("[type=submit]");btn.disabled=true;
try{const {error}=await sb.from("sl2_posts").insert({title,body,author_id:user.id});if(error)throw error;form.reset();report("#news-message","Новину опубліковано.");await loadData()}catch(e){report("#news-message","Не вдалося опублікувати новину.",true)}finally{btn.disabled=false}});
$("#photo-form").addEventListener("submit",async(e)=>{e.preventDefault();if(!sb||!isAdmin)return;const form=e.currentTarget,file=form.elements.photo.files[0],title=form.elements.title.value.trim();if(!file||!title)return;const allowed=["image/png","image/jpeg","image/webp"];if(!allowed.includes(file.type)||file.size>5*1024*1024){report("#photo-message","Потрібне JPEG, PNG або WebP до 5 МБ.",true);return;}const btn=form.querySelector("[type=submit]");btn.disabled=true;
const suffix={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}[file.type],path=user.id+"/"+crypto.randomUUID()+"."+suffix;
try{const up=await sb.storage.from("sl2-gallery").upload(path,file,{contentType:file.type,cacheControl:"3600",upsert:false});if(up.error)throw up.error;const saved=await sb.from("sl2_photos").insert({title,path,author_id:user.id});if(saved.error){await sb.storage.from("sl2-gallery").remove([path]);throw saved.error;}form.reset();report("#photo-message","Фото додано до галереї.");await loadData()}catch(e){report("#photo-message","Не вдалося завантажити фото. Перевір Storage та доступи.",true)}finally{btn.disabled=false}});
async function start(){if(configured){if(!window.supabase?.createClient){notify("Не вдалося завантажити бібліотеку Supabase.");}else{sb=window.supabase.createClient(cfg.supabaseUrl,cfg.supabaseKey,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:false}});await refreshAccount();sb.auth.onAuthStateChange((_event,session)=>{if(!session){user=null;username=null;isAdmin=false;renderAccount();if(location.hash==="#admin")go("account")}});}}
renderAccount();await loadData();go(decodeURIComponent(location.hash.slice(1))||"home");}
start().catch(()=>{renderAccount();go("home");notify("Помилка завантаження даних. Спробуй оновити сторінку.")});
})();