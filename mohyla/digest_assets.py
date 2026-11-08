"""Static CSS/JS/text constants for the digest pages (kept out of digest.py)."""
from __future__ import annotations

FONTS_HREF = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&"
              "family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap")

SITE_TITLE = "Могилянський ранок"
SITE_SUBTITLE = "Щоденний медіамонітор спільноти НаУКМА"

MONTHS_GEN = ("січня", "лютого", "березня", "квітня", "травня", "червня", "липня",
              "серпня", "вересня", "жовтня", "листопада", "грудня")
WEEKDAYS = ("понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя")

CATEGORY_LABELS = {"achievement": "Досягнення", "science": "Наука",
                   "students": "Студентство", "community": "Спільнота"}
KIND_LABELS = {"official": "офіційне", "media": "медіа", "social": "соцмережі"}
EVENT_KIND_LABELS = {"talk": "Лекція", "workshop": "Воркшоп", "meeting": "Зустріч",
                     "social": "Дозвілля", "performance": "Виступ",
                     "career_fair": "Ярмарок вакансій", "summer_school": "Школа, курс",
                     "recruitment": "Набір", "registration_deadline": "Дедлайн реєстрації",
                     "fundraiser": "Благодійність", "other": "Подія"}
ROLE_LABELS = {"alumnus": "випускник", "staff": "співробітник", "student": "студент"}

CSS = """
:root{--bg:#f7f5f0;--paper:#fffdf8;--ink:#1b1d22;--muted:#5d6370;--line:#e3dfd5;
--accent:#1d3b6f;--accent-soft:#e6ecf6;--gold:#a8842c;--ok:#2f6b3a;--bad:#a23b2c;
--off:#7a7f88;--serif:"Source Serif 4",Georgia,"Times New Roman",serif;
--sans:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#111318;--paper:#181b22;--ink:#e9e6df;
--muted:#9aa0ab;--line:#2a2f39;--accent:#9db8e8;--accent-soft:#1f2a3d;--gold:#d4b25a;
--ok:#7fc48b;--bad:#ec8a7a;--off:#8b909a}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 var(--sans)}
a{color:var(--accent)}
.wrap{max-width:860px;margin:0 auto;padding:0 16px}
.topnav{display:flex;justify-content:space-between;gap:12px;font-size:13px;
padding:12px 0;color:var(--muted)}
.topnav a{color:var(--muted);text-decoration:none}.topnav a:hover{color:var(--accent)}
.topnav .tabs{display:flex;flex-wrap:wrap;gap:4px 14px}
.topnav a[aria-current=page]{color:var(--accent);font-weight:600;
box-shadow:inset 0 -2px 0 var(--accent)}
.badge.ev{color:var(--accent);background:var(--accent-soft);border-color:transparent}
.place{margin:2px 0 0;font-size:14px;color:var(--ink)}
.mast{border-top:4px solid var(--accent);border-bottom:1px solid var(--line);
padding:20px 0 18px;margin-bottom:8px}
.mast .brand{font:600 13px var(--sans);letter-spacing:.12em;text-transform:uppercase;
color:var(--accent);margin:0}
.mast h1{font:700 clamp(30px,7vw,46px)/1.1 var(--serif);margin:6px 0 8px}
.mast .meta{color:var(--muted);font-size:14px;margin:0}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:14px 0}
.filters[hidden]{display:none}
.chip-btn{font:500 13px var(--sans);border:1px solid var(--line);background:var(--paper);
color:var(--ink);border-radius:999px;padding:5px 12px;cursor:pointer}
.chip-btn[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:var(--paper)}
.search{flex:1 1 180px;min-width:0;font:15px var(--sans);padding:7px 12px;
border:1px solid var(--line);border-radius:8px;background:var(--paper);color:var(--ink)}
h2.sec{font:600 13px var(--sans);letter-spacing:.1em;text-transform:uppercase;
color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:6px;margin:28px 0 4px}
.lead{display:grid;gap:14px;margin-top:12px}
.card{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h3{font:600 21px/1.28 var(--serif);margin:6px 0}
.card:first-child h3{font-size:clamp(23px,5vw,28px)}
.list{list-style:none;margin:0;padding:0}
.row{padding:14px 0;border-bottom:1px solid var(--line)}
.row h3{font:600 17px/1.35 var(--serif);margin:4px 0}
h3 a{color:var(--ink);text-decoration:none}h3 a:hover{color:var(--accent);text-decoration:underline}
.kick{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12px;color:var(--muted)}
.badge{font-weight:600;text-transform:uppercase;letter-spacing:.05em;font-size:10.5px;
padding:2px 7px;border-radius:4px;border:1px solid currentColor}
.badge.official{color:var(--accent);background:var(--accent-soft);border-color:transparent}
.badge.media{color:var(--ink)}
.badge.social{color:var(--gold)}
.cat{color:var(--accent);font-weight:600}
.snip{margin:4px 0 0;color:var(--muted);font-size:14.5px;display:-webkit-box;
-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.people{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.person{font-size:12.5px;background:var(--accent-soft);color:var(--ink);border-radius:999px;
padding:2px 10px;text-decoration:none}
.person small{color:var(--muted)}
a.person:hover{outline:1px solid var(--accent)}
.also{font-size:12.5px;color:var(--muted);margin-top:6px;overflow-wrap:anywhere}
.empty{color:var(--muted);font-style:italic;padding:16px 0}
.newp li{padding:6px 0;border-bottom:1px solid var(--line);font-size:15px}
footer{margin:40px 0 32px;font-size:13px;color:var(--muted)}
.tbl-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.st-ok{color:var(--ok)}.st-failed{color:var(--bad)}.st-disabled{color:var(--off)}
.archive li{padding:8px 0;border-bottom:1px solid var(--line);font:18px var(--serif)}
.is-hidden{display:none!important}
@media (min-width:720px){.lead{grid-template-columns:1fr 1fr}
.lead .card:first-child{grid-column:1/-1}}
"""

JS = """
(function(){
  var bar=document.querySelector('.filters'); if(!bar) return;
  bar.hidden=false;
  var items=[].slice.call(document.querySelectorAll('[data-cat]'));
  var btns=[].slice.call(bar.querySelectorAll('.chip-btn'));
  var q=bar.querySelector('.search'); var cat='';
  function apply(){
    var s=(q.value||'').trim().toLowerCase();
    items.forEach(function(el){
      var ok=(!cat||el.getAttribute('data-cat')===cat)&&
             (!s||el.textContent.toLowerCase().indexOf(s)>=0);
      el.classList.toggle('is-hidden',!ok);
    });
    document.querySelectorAll('section[data-group]').forEach(function(sec){
      var vis=sec.querySelector('[data-cat]:not(.is-hidden)');
      sec.classList.toggle('is-hidden',!vis);
    });
  }
  btns.forEach(function(b){b.addEventListener('click',function(){
    cat=b.getAttribute('data-filter');
    btns.forEach(function(x){x.setAttribute('aria-pressed',String(x===b));});
    apply();
  });});
  q.addEventListener('input',apply);
})();
"""
