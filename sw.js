/* Service worker — học ngoại tuyến. Trang chính đã chứa sẵn từ điển + trò chơi nên chỉ cần lưu lại chính nó. */
const V='vt-v2';
self.addEventListener('install',e=>{ e.waitUntil(caches.open(V).then(c=>c.addAll(['./','manifest.webmanifest','icon-192.png','icon-512.png']).catch(()=>{})).then(()=>self.skipWaiting())); });
self.addEventListener('activate',e=>{ e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==V).map(k=>caches.delete(k)))).then(()=>self.clients.claim())); });
self.addEventListener('fetch',e=>{
  const r=e.request; if(r.method!=='GET') return;
  const u=new URL(r.url);
  if(u.hostname.endsWith('supabase.co')||u.hostname.includes('youtube')||u.hostname.includes('ytimg')) return;   // dữ liệu động / video: để mạng xử lý
  if(u.pathname.includes('/audio/')||r.headers.has('range')) return;   // nhạc mp3 (file lớn, phát theo từng đoạn): để trình duyệt tự xử lý
  if(r.mode==='navigate'){   // trang: ưu tiên mạng, mất mạng thì dùng bản đã lưu
    e.respondWith(fetch(r).then(res=>{ const cp=res.clone(); caches.open(V).then(c=>c.put('./',cp)); return res; }).catch(()=>caches.match('./').then(x=>x||caches.match(r))));
    return;
  }
  e.respondWith(caches.match(r).then(hit=>{   // tài nguyên: dùng bản lưu, đồng thời làm mới nền
    const net=fetch(r).then(res=>{ if(res&&(res.ok||res.type==='opaque')){ const cp=res.clone(); caches.open(V).then(c=>c.put(r,cp)); } return res; }).catch(()=>hit);
    return hit||net;
  }));
});
