/* Workspace shell and disk-backed output library. The processing controls retain
   their original IDs and handlers, so navigation never recreates in-flight forms. */
const Studio = (() => {
  const paths = {
    studio: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16M3 10h6m-6 5h6m5-5 4 3-4 3z"/>',
    operate: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 10h18"/>',
    progress: '<path d="M4 17V9m5 8V4m5 13v-6m5 6V7"/>',
    edit: '<path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15z"/><path d="M13 20h8"/>',
    menu: '<path d="M4 6h16M4 12h10M4 18h16"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
    down: '<path d="m6 9 6 6 6-6"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h1m-1 6h1m-1 6h1"/>',
    upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    play: '<path d="m9 6 9 6-9 6z"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8m-8 4h5"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    drive: '<rect x="3" y="12" width="18" height="9" rx="2"/><path d="m3 12 3-9h12l3 9M7 16h.01M11 16h.01"/>',
    refresh: '<path d="M20 7V3l-3 3a8 8 0 1 0 3 10M20 3h-5"/>',
    back: '<path d="m11 5-7 7 7 7M4 12h16"/>',
    bolt: '<path d="m13 2-9 12h7l-1 8 10-13h-7z"/>',
  };
  const labels = {operate:'Vận hành', library:'Kho đầu ra', progress:'Tiến trình', editor:'Studio'};
  let library = {projects:[], summary:{projects:0,parts:0,complete:0,size_bytes:0}};
  let activePage = 'operate', activeProject = null, query = '', sort = 'recent', filter = 'all', view = 'grid';
  let loading = false, librarySignature = '', libraryError = '', status = {}, lastOutputs = '', toastTimer;
  const $ = (id) => document.getElementById(id);
  function icon(name) { return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.file}</svg>`; }
  function node(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; }
  function iconNode(name, cls='') { const n=node('span',cls); n.innerHTML=icon(name); return n; }
  function button(text, cls, action, glyph) {
    const n=node('button',cls); n.type='button'; if(glyph)n.append(iconNode(glyph)); n.append(document.createTextNode(text)); n.onclick=action; return n;
  }
  function bytes(size) { if(!size)return '0 B'; const i=Math.min(3,Math.floor(Math.log(size)/Math.log(1024))); return `${(size/1024**i).toLocaleString('vi-VN',{maximumFractionDigits:i>1?1:0})} ${['B','KB','MB','GB'][i]}`; }
  function date(value) { return value ? new Date(value*1000).toLocaleDateString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric'}) : 'Chưa có tệp'; }
  function plain(text) { return String(text || '').replace(/[\p{Extended_Pictographic}\uFE0F\u200D\u20E3]/gu,'').replace(/\s+/g,' ').trim(); }
  function toast(message,error=false) {
    let n=$('studioToast'); if(!n){n=node('div','app-toast');n.id='studioToast';n.setAttribute('role','status');document.body.append(n);}
    n.className=`app-toast${error?' error':''}`;n.textContent=message;n.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{n.hidden=true;},4500);
  }
  function heading(kicker,title,description,actions='') {
    return `<div class="page-heading"><div><div class="eyebrow">${kicker}</div><h1>${title}</h1><p>${description}</p></div><div class="heading-actions">${actions}</div></div>`;
  }
  function mount() {
    document.title='Video Studio — Không gian sản xuất';
    document.body.classList.add('studio-app');
    if(localStorage.getItem('studio.expanded')==='true')document.body.classList.add('sidebar-expanded');
    const oldHeader=document.querySelector('header.topbar');
    const legacyMain=document.querySelector('main.container');
    const cards=[...legacyMain.querySelectorAll('section.card')];
    const editor=document.querySelector('.full-width-section');
    const finished=$('finishedBox');
    const side=node('aside','studio-sidebar');side.id='studioSidebar';side.setAttribute('aria-label','Điều hướng chính');
    side.innerHTML=`<a class="studio-brand" href="#/operate"><span class="studio-mark">${icon('studio')}</span><div><strong>Video Studio</strong><small>Production workspace</small></div></a>
      <div class="nav-caption">KHÔNG GIAN LÀM VIỆC</div><nav class="studio-nav" aria-label="Trang làm việc">${Object.entries(labels).map(([key,label])=>`<button type="button" data-page-nav="${key}" title="${label}">${icon(key==='library'?'folder':key==='editor'?'edit':key)}<span>${label}</span>${key==='library'?'<span class="nav-count" id="navLibraryCount">0</span>':''}${key==='progress'?'<span class="nav-count" id="navRunCount" hidden>0%</span>':''}</button>`).join('')}</nav>
      <div class="sidebar-projects"><button class="sidebar-project-toggle" id="projectTreeToggle" aria-expanded="true">CÁC BỘ GẦN ĐÂY ${icon('down')}</button><div class="project-tree" id="sidebarProjectTree"></div></div>
      <div class="sidebar-bottom"><div class="local-status"><span class="status-dot"></span> Không gian trên máy của bạn</div><div class="sidebar-disk" id="sidebarDiskText">Đang kiểm tra dung lượng…</div><details class="system-details"><summary>Thông tin hệ thống</summary><div id="sidebarSystemInfo"></div></details></div>`;
    const top=node('header','studio-topbar');
    top.innerHTML=`<div class="topbar-left"><button class="sidebar-toggle" id="sidebarToggle" title="Mở rộng thanh bên" aria-label="Mở rộng thanh bên">${icon('menu')}</button><div class="studio-crumbs"><span>Không gian làm việc</span>${icon('chevron')}<strong id="studioCrumb">Vận hành</strong></div></div><div class="topbar-actions"><button class="topbar-run" id="topbarRun"><span class="status-dot"></span><span id="topbarRunText">Sẵn sàng</span></button><button class="btn btn-outline" id="topbarOpenOutput">${icon('folder')} Thư mục output</button></div>`;
    const workspace=node('div','studio-workspace');workspace.id='studioWorkspace';
    workspace.innerHTML=`<section class="studio-page" data-page="operate" id="pageOperate">${heading('Sản xuất video','Không gian vận hành','Chọn nguồn, chia phần và hoàn thiện đầu ra theo một quy trình.',`<button class="btn btn-outline" id="operateToLibrary">${icon('folder')} Xem kho đầu ra</button>`)}
      <div class="operate-summary"><div class="summary-metric"><small>NGUỒN ĐẦU VÀO</small><strong id="operateSourceCount">Chưa có nguồn</strong></div><div class="summary-metric"><small>PHẦN ĐÃ CHỌN</small><strong id="operateSelectedCount">0 phần</strong></div><div class="summary-metric"><small>QUY TRÌNH</small><strong id="operateWorkflow">Video · SRT · MP3</strong></div><div class="summary-hint">${icon('check')} Lưu riêng từng phần</div></div><div class="operate-grid"><div class="operate-left" id="operateLeft"></div><div id="operateSettings"></div></div></section>
      <section class="studio-page" data-page="library" id="pageLibrary">${heading('Tài nguyên của bạn','Kho đầu ra','Mỗi bộ một thư mục. Mỗi phần có video, phụ đề và giọng thuyết minh.',`<button class="btn btn-outline" id="libraryRefresh">${icon('refresh')} Làm mới</button><button class="btn btn-primary" id="libraryNewTask">${icon('plus')} Tạo tác vụ</button>`)}
        <div class="library-stats">${[['projects','Bộ trong kho','folder'],['parts','Tổng số phần','file'],['complete','Phần đủ 3 tệp','check'],['size','Dung lượng đầu ra','drive']].map(([id,label,glyph])=>`<div class="stat-tile"><div><small>${label}</small><strong id="libraryStat-${id}">0</strong></div><span class="stat-icon">${icon(glyph)}</span></div>`).join('')}</div>
        <div class="library-panel"><div class="library-toolbar"><h2 id="librarySectionTitle">Các bộ trong kho</h2><label class="library-search">${icon('search')}<input id="librarySearch" type="search" placeholder="Tìm bộ hoặc phần…" aria-label="Tìm trong kho đầu ra"/></label><select class="library-filter" id="libraryFilter" aria-label="Lọc trạng thái"><option value="all">Mọi trạng thái</option><option value="complete">Đủ video, SRT, MP3</option><option value="pending">Chưa đầy đủ</option><option value="error">Cần thử lại</option></select><select class="library-sort" id="librarySort" aria-label="Sắp xếp kho"><option value="recent">Mới cập nhật</option><option value="name">Theo tên / số phần</option></select><div class="view-mode" id="libraryViewModes"><button title="Dạng lưới" aria-label="Dạng lưới" data-view="grid" class="active">${icon('grid')}</button><button title="Dạng danh sách" aria-label="Dạng danh sách" data-view="list">${icon('list')}</button></div></div>
        <div class="library-breadcrumb" id="libraryBreadcrumb" hidden></div><div id="libraryBulkHost"></div><div id="libraryContent"></div><div class="library-footer"><span id="libraryFooterText">Dữ liệu được đọc từ thư mục output/</span><button class="library-back" id="libraryBack" hidden>${icon('back')} Tất cả các bộ</button></div></div></section>
      <section class="studio-page" data-page="progress" id="pageProgress">${heading('Theo dõi sản xuất','Tiến trình xử lý','Xem trạng thái hiện tại và kết quả của từng bước.',`<button class="btn btn-outline" id="progressToLibrary">${icon('folder')} Xem đầu ra</button>`)}<div class="progress-overview"><div><h2 id="runOverviewTitle">Sẵn sàng cho tác vụ mới</h2><small id="runOverviewHint">Chọn video và các phần cần xử lý trong trang Vận hành.</small></div><button class="btn btn-danger" id="runStopButton" hidden>Dừng tác vụ</button></div><div id="progressCardHost"></div></section>
      <section class="studio-page editor-panel" data-page="editor" id="pageEditor">${heading('Hậu kỳ','Phụ đề & âm thanh','Xem trước video, chỉnh phụ đề và tạo lại giọng đọc cho từng phần.',`<button class="btn btn-outline" id="editorToLibrary">${icon('folder')} Chọn phần từ kho</button>`)}<div id="editorHost"></div></section>`;
    document.body.insertBefore(side,oldHeader);document.body.insertBefore(top,oldHeader);document.body.insertBefore(workspace,legacyMain);
    ['osBadge','gpuBadge','diskBadge'].forEach(id=>$('sidebarSystemInfo').append($(id)));
    oldHeader.remove();
    $('operateLeft').append(cards[0],cards[1]);$('operateSettings').append(cards[2]);$('progressCardHost').append(cards[3]);$('editorHost').append(editor);
    legacyMain.remove();
    styleOperations(cards);styleEditor(editor);
    // Reuse the processing buttons while the library provides their selection.
    const controls=finished.children[1];controls.className='library-bulk';controls.removeAttribute('style');
    controls.querySelectorAll('button').forEach(b=>{b.textContent=plain(b.textContent);b.removeAttribute('style');});
    const labelsByMode={srt:'Tạo SRT',mp3:'Tạo MP3',full:'Làm tiếp SRT → MP3'};
    controls.querySelectorAll('[data-workflow-action]').forEach(b=>{for(const [mode,label] of Object.entries(labelsByMode))if(b.getAttribute('onclick').includes(`'${mode}'`))b.textContent=label;});
    $('libraryBulkHost').append(controls);finished.remove();$('libraryBulkHost').hidden=true;
    const logs=$('logBox'),details=node('details','progress-logs');details.open=true;const summary=node('summary','', 'Nhật ký xử lý');details.append(summary,logs);cards[3].append(details);
    const stages=node('div','progress-stage-list');stages.id='runStageList';stages.innerHTML=['Video','Nhận diện','Dịch SRT','Thuyết minh'].map((s,i)=>`<span data-stage="${i}"><i>${i+1}</i>${s}</span>`).join('');cards[3].insertBefore(stages,cards[3].children[1]);
    $('sidebarToggle').onclick=()=>{if(innerWidth<=620)document.body.classList.toggle('mobile-nav-open');else{document.body.classList.toggle('sidebar-expanded');localStorage.setItem('studio.expanded',document.body.classList.contains('sidebar-expanded'));}};
    const shade=node('div','sidebar-shade');shade.onclick=()=>document.body.classList.remove('mobile-nav-open');document.body.append(shade);
    document.querySelectorAll('[data-page-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.pageNav));
    $('projectTreeToggle').onclick=()=>{const expanded=$('projectTreeToggle').getAttribute('aria-expanded')==='true';$('projectTreeToggle').setAttribute('aria-expanded',String(!expanded));$('sidebarProjectTree').hidden=expanded;};
    ['operateToLibrary','progressToLibrary','editorToLibrary'].forEach(id=>$(id).onclick=()=>navigate('library'));
    $('topbarOpenOutput').onclick=()=>openOutputFolder();$('libraryRefresh').onclick=()=>refresh(true);$('libraryNewTask').onclick=()=>{navigate('operate');$('dropzone').focus();};
    $('topbarRun').onclick=()=>navigate('progress');$('runStopButton').onclick=()=>stopPipeline();$('libraryBack').onclick=()=>navigate('library');
    $('librarySearch').oninput=e=>{query=e.target.value;renderLibrary();};$('librarySort').onchange=e=>{sort=e.target.value;renderLibrary();};$('libraryFilter').onchange=e=>{filter=e.target.value;renderLibrary();};
    document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;renderLibrary();});
    const oldRenderPlan=renderPlan;renderPlan=function(plan){oldRenderPlan(plan);updatePlan(plan);};
    const oldPreview=previewSpecificVideo;previewSpecificVideo=function(path){navigate('editor');oldPreview(path);};
    window.addEventListener('hashchange',route);window.addEventListener('keydown',e=>{if(e.key==='Escape')document.body.classList.remove('mobile-nav-open');});
    installFileDrop();route();renderLibrary();refresh();setInterval(()=>refresh(),5000);
  }
  let importingSrt=false;
  function droppedFileUrl(transfer){
    return [transfer.getData('text/uri-list'),transfer.getData('text/plain')]
      .flatMap(value=>value.split(/\r?\n/)).map(value=>value.trim())
      .find(value=>/^file:\/\//i.test(value))||'';
  }
  async function importSubtitle(file,sourcePath=''){
    if(importingSrt){toast('Đang mở phụ đề. Hãy chờ một chút.');return;}
    importingSrt=true;
    try{
      const payload=file?{filename:file.name,text:await file.text(),source_path:sourcePath||file.path||''}:{source_path:sourcePath};
      const response=await fetch('/api/srt/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if(response.status===404)throw new Error('Hãy mở lại chay_tool.command để cập nhật chức năng kéo thả SRT.');
      const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.message||'Không mở được file phụ đề.');
      srtRowsData=data.srt_rows;renderSrtTable();renderSrtTarget(data);
      if(data.active_video_for_srt&&data.active_video_for_srt!==currentPreviewLoadedPath)loadVideoIntoPreviewPlayer(data.active_video_for_srt,false);
      $('srtStatusLabel').textContent=data.srt_status_msg;
      navigate('editor');toast(`Đã mở ${srtRowsData.length} câu phụ đề.`);
    }catch(error){toast(error.message||'Không đọc được file SRT.',true);}
    finally{importingSrt=false;}
  }
  function installFileDrop(){
    const hasFile=transfer=>Array.from(transfer?.types||[]).some(type=>type==='Files'||type==='text/uri-list');
    document.addEventListener('dragover',event=>{if(hasFile(event.dataTransfer)){event.preventDefault();event.dataTransfer.dropEffect='copy';document.body.classList.add('studio-file-drag');}},true);
    document.addEventListener('dragleave',event=>{if(!event.relatedTarget)document.body.classList.remove('studio-file-drag');},true);
    document.addEventListener('dragend',()=>document.body.classList.remove('studio-file-drag'),true);
    document.addEventListener('drop',event=>{
      const transfer=event.dataTransfer;if(!transfer)return;
      const files=Array.from(transfer.files||[]),url=droppedFileUrl(transfer);
      if(!files.length&&!url)return;
      // Capture at document level so a drop anywhere in Studio cannot navigate to file://.
      event.preventDefault();event.stopPropagation();document.body.classList.remove('studio-file-drag');
      if(files.length===1&&/\.srt$/i.test(files[0].name)){void importSubtitle(files[0],url);return;}
      if(!files.length&&/\.srt$/i.test(url.split(/[?#]/)[0])){void importSubtitle(null,url);return;}
      if(files.length&&files.every(file=>/\.(mp4|mkv|mov|avi|webm|flv|ts|m4v)$/i.test(file.name))){navigate('operate');void handleDrop(event).catch(error=>toast(error.message,true));return;}
      toast('Thả một file .SRT để mở phụ đề, hoặc thả video để thêm nguồn.',true);
    },true);
  }
  function styleOperations(cards) {
    const names=['Nguồn đầu vào','Chia phần & lựa chọn','Thông số xuất','Tác vụ hiện tại'];
    cards.forEach((card,i)=>{const title=card.querySelector('.step-title');if(title){const spans=title.querySelectorAll('span');spans[spans.length-1].textContent=names[i];}});
    const source=cards[0];source.querySelector('.step-header>span').textContent='Tệp video hoặc liên kết';
    source.querySelector('.dropzone-icon').innerHTML=icon('upload');source.querySelector('h3').textContent='Thả video để bắt đầu';source.querySelector('.dropzone p').textContent='Thêm một video dài hoặc cả bộ video từ máy của bạn.';
    source.querySelectorAll('.picker-buttons button').forEach((b,i)=>{b.textContent=['Chọn video','Chọn thư mục','Dán liên kết'][i];b.prepend(iconNode(['file','folder','plus'][i]));});$('dropzone').tabIndex=-1;
    const smallLabels={pill15m:'15 phút',pill30m:'30 phút',pill1h:'1 giờ',pill3h:'3 giờ',pill5h:'5 giờ',pillSingle:'Gộp một tệp'};Object.entries(smallLabels).forEach(([id,text])=>$(id).textContent=text);
    const config=cards[2];config.classList.add('config-card');
    const topChild=element=>{while(element.parentElement!==config)element=element.parentElement;return element;};
    const title=config.querySelector('.step-header'),name=topChild($('projectNameInput')),res=topChild($('resolutionSelect')),workflow=topChild($('workflowModeSelect')),footer=topChild($('startBtn'));
    const advanced=node('details','config-advanced');advanced.append(node('summary','', 'Cài đặt nâng cao'));
    [...config.children].filter(e=>![title,name,res,workflow,footer].includes(e)).forEach(e=>advanced.append(e));
    config.querySelectorAll('[style]').forEach(e=>{if(e.style.background||e.style.backgroundColor){if(e.tagName==='DIV'&&!e.className)e.classList.add('setting-group');}['background','background-color','color','border','border-color','box-shadow'].forEach(k=>e.style.removeProperty(k));});
    workflow.removeAttribute('style');workflow.className='workflow-panel';workflow.children[0].removeAttribute('style');workflow.children[0].className='workflow-title';workflow.children[0].textContent='Quy trình cho mỗi phần';
    const help=workflow.lastElementChild;help.removeAttribute('style');help.className='workflow-help';help.textContent='Hoàn tất từng phần trước khi sang phần tiếp theo. Video, SRT và MP3 được lưu chung trong thư mục của phần.';
    footer.removeAttribute('style');footer.className='config-footer';name.querySelector('label').textContent='Tên bộ / dự án';config.replaceChildren(title,name,res,workflow,advanced,footer);
    const replacements={hardcore:'Tùy chỉnh nâng cao',medium:'Hiệu chỉnh vừa',basic:'Hiệu chỉnh nhẹ',off:'Giữ hình ảnh và tốc độ gốc'};
    [...$('antiCopyrightLevel').options].forEach(o=>{o.textContent=replacements[o.value]||o.textContent;});
    $('antiCopyrightLevel').closest('.form-group').querySelector('label').textContent='Hiệu chỉnh hình ảnh & âm thanh';
    for(const card of cards.slice(0,3)){
      const walker=document.createTreeWalker(card,NodeFilter.SHOW_TEXT);let n;while(n=walker.nextNode()){if(n.parentElement.tagName!=='SCRIPT'&&n.textContent.trim())n.textContent=plain(n.textContent);}
    }
    name.querySelector('label').textContent='Tên bộ / dự án';
  }
  let subtitleQuery='', selectedCue=-1, timelineZoom=0, timelineDuration=30, waveformPaths={};
  const waveformCache=new Map();
  let timelineView=null,timelineCursor=0,timelineFrame=0,waveTimer=0,timelineRows=[];
  const waveRequests={},waveData={};
  function field(parent,id,label) {
    const el=$(id);const group=node('div','inspector-field');
    if(label){const l=node('label','',label);l.htmlFor=id;group.append(l);}
    el.removeAttribute('style');group.append(el);parent.append(group);return group;
  }
  function checkField(parent,id,label) {
    const wrap=node('label','inspector-check'),el=$(id);el.removeAttribute('style');wrap.append(el,document.createTextNode(label));parent.append(wrap);
  }
  function styleEditor(editor) {
    const work=node('div','editor-workbench');
    work.innerHTML=`<div class="editor-commandbar"><div class="editor-document"><span class="document-icon">${icon('studio')}</span><div><strong>Studio biên tập</strong><small id="editorDocumentName">Chọn một phần để bắt đầu</small></div></div><div class="editor-command-actions" id="editorCommandActions"></div></div>
      <div class="editor-columns"><section class="subtitle-panel"><div class="subtitle-header"><strong id="subtitleCount">0 câu phụ đề</strong><button class="icon-button" id="editorAddCue" title="Thêm câu phụ đề" aria-label="Thêm câu phụ đề">${icon('plus')}</button></div><label class="cue-search">${icon('search')}<input id="cueSearchInput" placeholder="Tìm trong phụ đề…" aria-label="Tìm trong phụ đề"/></label><div class="subtitle-tools" id="subtitleTools"></div><div class="subtitle-list" id="studioSubtitleList"></div><div class="subtitle-bottom"><span id="editorCueHint">Tiếng Trung → Tiếng Việt</span><button id="editorFindReplace" title="Tìm và thay thế">Thay thế từ</button></div><details class="editor-replace" id="editorReplace"><summary>Tìm và thay thế</summary><div id="editorReplaceHost"></div></details></section>
      <section class="preview-panel"><div class="preview-source" id="editorSource"></div><div class="preview-stage" id="editorStage"><div class="preview-empty" id="editorPreviewEmpty">${icon('studio')}<strong>Khung hình của bạn ở đây</strong><span>Chọn video từ kho đầu ra để xem và biên tập.</span><button class="btn btn-outline" id="editorEmptyLibrary">${icon('folder')} Mở kho đầu ra</button></div></div><div class="preview-transport"><button class="transport-play" id="editorPlay" aria-label="Phát hoặc tạm dừng video">${icon('play')}</button><span id="editorTime">00:00 / 00:00</span><div class="transport-spacer"></div><select id="editorSpeed" aria-label="Tốc độ phát"><option value="1">1,0×</option><option value="1.25">1,25×</option><option value="1.5">1,5×</option><option value="2">2,0×</option></select><button class="icon-button" id="editorFullscreen" title="Toàn màn hình" aria-label="Toàn màn hình">⛶</button></div></section>
      <aside class="inspector-panel"><div class="inspector-tabs" role="tablist" aria-label="Tùy chỉnh video">${[['sub','Phụ đề','file'],['voice','Giọng','bolt'],['image','Hình','grid'],['audio','Tiếng','progress']].map(([id,label,glyph],i)=>`<button role="tab" aria-selected="${i===0}" aria-controls="inspector-${id}" id="inspector-tab-${id}" data-inspector="${id}" class="${i===0?'active':''}">${icon(glyph)}<span>${label}</span></button>`).join('')}</div><div class="inspector-content"><section id="inspector-sub" role="tabpanel" aria-labelledby="inspector-tab-sub"><div class="inspector-note">Kéo phụ đề trực tiếp trên khung hình để đổi vị trí. Bấm phát để kiểm tra khớp lời.</div><h3>Kiểu phụ đề</h3><div class="subtitle-presets" id="subtitlePresets"></div></section><section id="inspector-voice" role="tabpanel" aria-labelledby="inspector-tab-voice" hidden><h3>Thuyết minh tiếng Việt</h3></section><section id="inspector-image" role="tabpanel" aria-labelledby="inspector-tab-image" hidden><h3>Khung hình & vùng làm mờ</h3><p class="inspector-help">Kéo hoặc co giãn vùng làm mờ trên video. Thông số vùng dùng chung với cài đặt ở trang Vận hành.</p></section><section id="inspector-audio" role="tabpanel" aria-labelledby="inspector-tab-audio" hidden><h3>Bàn trộn âm thanh</h3></section></div></aside></div>
      <section class="studio-timeline"><div class="timeline-toolbar"><strong>${icon('list')} Timeline</strong><button class="timeline-tool" id="timelineBack">Về đầu</button><span class="timeline-scale" id="timelineScaleLabel"></span><label class="timeline-goto"><span>Tới</span><input id="timelineGoto" aria-label="Tới mốc thời gian" placeholder="00:00:00,000" title="Nhập giờ:phút:giây hoặc số giây, rồi nhấn Enter"/></label><div class="timeline-zoom"><button class="timeline-tool" id="timelineZoomOut" aria-label="Thu nhỏ timeline" title="Thu nhỏ timeline">−</button><input type="range" min="0" max="100" step="1" value="0" id="timelineZoom" aria-label="Mức zoom timeline"/><button class="timeline-tool" id="timelineZoomIn" aria-label="Phóng to timeline" title="Phóng to timeline">+</button></div><select id="timelineSpan" aria-label="Khoảng thời gian hiển thị"><option value="all">Toàn bộ</option><option value="600">10 phút</option><option value="60">1 phút</option><option value="10">10 giây</option><option value="custom" hidden>Tùy chỉnh</option></select><button class="timeline-tool" id="timelineFit">Vừa khung</button></div><div class="timeline-body"><div class="timeline-labels"><div></div><div><i class="track-dot original"></i>Tiếng gốc</div><div><i class="track-dot narration"></i>Giọng lồng</div><div><i class="track-dot subtitles"></i>Phụ đề</div></div><div class="timeline-scroll" id="timelineScroll"><div class="timeline-canvas" id="timelineCanvas"><div class="timeline-ruler" id="timelineRuler"></div><div class="wave-track original" id="originalWaveTrack"><span>Chọn video để hiển thị âm thanh gốc</span></div><div class="wave-track narration" id="narrationWaveTrack"><span>Chưa có MP3 thuyết minh</span></div><div class="subtitle-track" id="subtitleTrack"></div><div class="timeline-playhead" id="timelinePlayhead"></div></div></div></div></section><div class="editor-statusbar" id="editorStatusHost"></div>`;
    editor.append(work);
    const command=work.querySelector('#editorCommandActions');
    command.append(button('Chọn phần','btn btn-outline',()=>navigate('library'),'folder'),button('Lưu SRT','btn btn-outline',()=>saveEditedSrt(),'file'));
    const exportButton=$('capcutExportBtn');exportButton.removeAttribute('style');exportButton.textContent='Xuất video';exportButton.className='btn btn-primary';exportButton.prepend(iconNode('upload'));command.append(exportButton);
    work.querySelector('#editorSource').append($('previewVideoSelect'));
    const preview=$('previewPlayerWrap');preview.removeAttribute('style');work.querySelector('#editorStage').append(preview);
    const player=$('previewVideoPlayer');player.removeAttribute('style');player.controls=false;
    const blur=$('blurZoneOverlay');blur.querySelector('span').textContent='Kéo để đổi vùng làm mờ';
    const sub=$('inspector-sub'),voice=$('inspector-voice'),image=$('inspector-image'),audio=$('inspector-audio');
    // These nodes are moved, preserving the backend's IDs and existing handlers.
    field(sub,'capcutSubColorSelect','Màu chữ');field(sub,'capcutSubSizeInput','Cỡ chữ (ở độ cao 1080p)');
    checkField(sub,'capcutSubBoxCheck','Nền đen sau chữ');checkField(sub,'capcutBurnSubCheck','In phụ đề vào video khi xuất');
    field(voice,'ttsVoiceSelect','Giọng đọc chung');const tts=$('ttsOnlyMp3Btn');tts.removeAttribute('style');tts.textContent='Tạo MP3 thuyết minh';voice.append(tts);
    voice.append(node('h3','', 'Nhận diện & dịch phụ đề'));field(voice,'whisperModelSelect','Mô hình Whisper');voice.append(button('Tách và dịch phụ đề','btn btn-outline',()=>autoTranscribeVideo(),'file'));
    const blurButton=$('blurNowBtn');blurButton.removeAttribute('style');blurButton.textContent='Áp dụng làm mờ video';image.append(blurButton,button('Đặt lại vị trí chữ & vùng mờ','btn btn-outline',()=>resetCapcutOverlayPositions(),'refresh'));
    field(audio,'capcutAudioSelect','File thuyết minh');audio.append(button('Chọn MP3 khác','btn btn-outline',()=>pickExternalMp3File(),'folder'));
    field(audio,'ttsAudioPreviewPlayer','Nghe riêng thuyết minh');checkField(audio,'syncMp3WithVideoCheck','Phát MP3 đồng bộ với video');
    for(const [id,label,valueId] of [['capcutTtsVolInput','Giọng thuyết minh','capcutTtsVolLabel'],['capcutOrigVolInput','Tiếng gốc / nhạc nền','capcutOrigVolLabel']]){const group=field(audio,id,label);const val=$(valueId);val.removeAttribute('style');group.append(val);}
    audio.append(button('Tải MP3 về máy','btn btn-outline',()=>downloadCurrentMp3File(),'upload'));
    const statusLabel=$('srtStatusLabel'),targetLabel=$('srtTargetLabel');statusLabel.removeAttribute('style');targetLabel.removeAttribute('style');work.querySelector('#editorStatusHost').append(statusLabel,targetLabel);
    const replace=editor.querySelector('.find-replace-bar');replace.removeAttribute('style');replace.querySelectorAll('[style]').forEach(e=>e.removeAttribute('style'));replace.querySelector('span').textContent='Từ cần thay';replace.querySelector('button').textContent='Thay thế tất cả';work.querySelector('#editorReplaceHost').append(replace);
    const srtInput=node('input');srtInput.type='file';srtInput.accept='.srt';srtInput.hidden=true;srtInput.id='studioSrtFileInput';
    srtInput.onchange=()=>{const file=srtInput.files[0];if(file)void importSubtitle(file);srtInput.value='';};work.append(srtInput);
    work.querySelector('#subtitleTools').append(button('Mở SRT','subtle-button',()=>srtInput.click(),'folder'),button('Tạo phụ đề','subtle-button',()=>autoTranscribeVideo(),'bolt'));
    editor.replaceChildren(work);
    const presets=[['Cổ điển','white',false],['Phim','white',true],['Nền hộp','yellow',true],['TikTok','yellow',false],['Xanh sáng','cyan',false],['Lá xanh','green',true]];
    presets.forEach(([name,color,box],i)=>{const b=node('button',`subtitle-preset preset-${i}`);b.type='button';b.append(node('strong','', 'Xin chào các bạn'),node('span','',name));b.dataset.color=color;b.dataset.box=String(box);b.onclick=()=>{$('capcutSubColorSelect').value=color;$('capcutSubBoxCheck').checked=box;updateCapcutSubPreviewStyle();syncPresets();};$('subtitlePresets').append(b);});
    ['capcutSubColorSelect','capcutSubBoxCheck'].forEach(id=>$(id).addEventListener('change',syncPresets));syncPresets();
    document.querySelectorAll('[data-inspector]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-inspector]').forEach(t=>{const active=t===b;t.classList.toggle('active',active);t.setAttribute('aria-selected',String(active));$(`inspector-${t.dataset.inspector}`).hidden=!active;});});
    $('editorEmptyLibrary').onclick=()=>navigate('library');$('editorAddCue').onclick=()=>addSrtRow();
    $('cueSearchInput').oninput=e=>{subtitleQuery=e.target.value;renderEditor();};$('editorFindReplace').onclick=()=>{$('editorReplace').open=!$('editorReplace').open;};
    $('editorPlay').onclick=()=>{if(!player.getAttribute('src')){toast('Chọn một video từ kho đầu ra trước.');return;}if(player.paused)player.play().catch(()=>toast('Không phát được định dạng video này.',true));else player.pause();};
    $('editorSpeed').onchange=e=>setPreviewPlaybackRate(Number(e.target.value));$('editorFullscreen').onclick=()=>preview.requestFullscreen?.().catch(()=>{});
    $('timelineBack').onclick=()=>seekTimeline(0,true);
    $('timelineFit').onclick=()=>setTimelineZoom(0,0,0);
    $('timelineZoom').oninput=e=>setTimelineZoom(Number(e.target.value));
    $('timelineZoomOut').onclick=()=>setTimelineZoom(timelineZoom-8);
    $('timelineZoomIn').onclick=()=>setTimelineZoom(timelineZoom+8);
    $('timelineSpan').onchange=e=>{if(e.target.value==='all')setTimelineZoom(0,0,0);else setTimelineZoom(TimelineMath.zoomForSpan(timelineDuration,$('timelineScroll').clientWidth,Number(e.target.value)));};
    $('timelineGoto').onkeydown=e=>{if(e.key!=='Enter')return;const value=e.target.value.trim();if(!/^(?:\d+:)?(?:[0-5]?\d:)?\d+(?:[,.]\d{1,3})?$/.test(value)){toast('Nhập mốc như 01:23:45,500 hoặc số giây.',true);return;}const time=parseSrtTimeToSec(value);if(!Number.isFinite(time)||time>timelineDuration){toast('Mốc thời gian nằm ngoài video.',true);return;}seekTimeline(time,true);};
    $('timelineScroll').addEventListener('scroll',scheduleTimelinePaint,{passive:true});
    $('timelineScroll').addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();const box=$('timelineScroll').getBoundingClientRect(),pixel=Math.max(0,Math.min(box.width,e.clientX-box.left));const at=(timelineView.scrollLeft+pixel)/timelineView.pixelsPerSecond;setTimelineZoom(timelineZoom+(e.deltaY<0?5:-5),at,pixel);},{passive:false});
    $('timelineCanvas').onclick=e=>{if(e.target.closest('.timeline-clip'))return;const rect=$('timelineCanvas').getBoundingClientRect();seekTimeline((e.clientX-rect.left)/timelineView.pixelsPerSecond);};
    new ResizeObserver(()=>{if(activePage==='editor')renderTimeline();}).observe($('timelineScroll'));
    player.addEventListener('timeupdate',syncPlayback);player.addEventListener('play',syncPlayback);player.addEventListener('pause',syncPlayback);
    player.addEventListener('loadedmetadata',()=>{renderTimeline();syncPlayback();updateCapcutSubPreviewStyle();});
    new ResizeObserver(()=>{if(activePage==='editor')updateCapcutSubPreviewStyle();}).observe($('editorStage'));
    player.addEventListener('loadstart',()=>{waveformPaths={};renderTimeline();syncPlayback();});
    $('ttsAudioPreviewPlayer').addEventListener('loadedmetadata',()=>{renderTimeline();syncPlayback();});
    renderEditor();
  }
  function syncPresets(){document.querySelectorAll('.subtitle-preset').forEach(b=>{const active=b.dataset.color===$('capcutSubColorSelect').value&&b.dataset.box===String($('capcutSubBoxCheck').checked);b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});}
  function timeLabel(sec){sec=Math.max(0,Number(sec)||0);const hours=Math.floor(sec/3600);return `${hours?String(hours).padStart(2,'0')+':':''}${String(Math.floor(sec/60)%60).padStart(2,'0')}:${String(Math.floor(sec)%60).padStart(2,'0')}`;}
  function renderEditor(){
    const list=$('studioSubtitleList');if(!list)return;list.replaceChildren();$('subtitleCount').textContent=`${srtRowsData.length} câu phụ đề`;
    const q=subtitleQuery.toLocaleLowerCase('vi');
    if(!srtRowsData.length){const empty=node('div','subtitle-empty');empty.append(iconNode('file'),node('strong','','Chưa có phụ đề'),node('p','','Mở file SRT có sẵn hoặc tạo phụ đề từ video đang chọn.'));list.append(empty);}
    srtRowsData.forEach((row,idx)=>{
      if(q&&!`${row.vi_text||''} ${row.zh_text||''}`.toLocaleLowerCase('vi').includes(q))return;
      const cue=node('article','subtitle-cue');cue.dataset.cue=idx;const meta=node('div','cue-meta');
      meta.append(node('span','cue-number',String(idx+1)));
      for(const [field,label] of [['start','Bắt đầu'],['end','Kết thúc']]){const input=node('input','cue-time');input.value=row[field]||'00:00:00,000';input.setAttribute('aria-label',`${label} câu ${idx+1}`);input.onchange=()=>{const value=input.value.trim();if(!/^\d{2,}:\d{2}:\d{2}[,.]\d{3}$/.test(value)||!Number.isFinite(parseSrtTimeToSec(value))){input.value=row[field];toast('Dùng định dạng 00:00:00,000 cho mốc thời gian.',true);return;}const start=field==='start'?parseSrtTimeToSec(value):parseSrtTimeToSec(row.start),end=field==='end'?parseSrtTimeToSec(value):parseSrtTimeToSec(row.end);if(start>=end){input.value=row[field];toast('Mốc kết thúc cần lớn hơn mốc bắt đầu.',true);return;}updateSrtCell(idx,field,value);renderTimeline();};meta.append(input);if(field==='start')meta.append(node('span','','→'));}
      const play=button('','cue-play',()=>{seekTimeline(parseSrtTimeToSec(row.start),true);if($('previewVideoPlayer').getAttribute('src'))seekPreviewToSrtRow(idx);highlightCue(idx);syncPlayback();},'play');play.title=`Phát câu ${idx+1}`;play.setAttribute('aria-label',play.title);meta.append(play);cue.append(meta);
      if(row.zh_text){const zh=node('div','cue-original',row.zh_text);cue.append(zh);}
      const text=node('textarea','cue-translation');text.value=row.vi_text||'';text.rows=2;text.setAttribute('aria-label',`Bản dịch câu ${idx+1}`);text.onfocus=()=>{selectedCue=idx;highlightCue(idx);};text.oninput=()=>{updateSrtCell(idx,'vi_text',text.value);if(timelineRows[idx])timelineRows[idx].text=text.value;const clip=$(`timeline-cue-${idx}`);if(clip)clip.textContent=text.value;onPreviewTimeUpdate();};cue.append(text);
      const footer=node('div','cue-footer');const count=node('span','',`${(row.vi_text||'').length} ký tự`);text.addEventListener('input',()=>count.textContent=`${text.value.length} ký tự`);footer.append(count);const del=button('Xóa câu','cue-delete',()=>deleteSrtRow(idx));del.setAttribute('aria-label',`Xóa câu ${idx+1}`);footer.append(del);cue.append(footer);list.append(cue);
    });
    if(srtRowsData.length&&!list.children.length)list.append(node('div','subtitle-empty','Không có câu khớp từ khóa.'));
    highlightCue(selectedCue);renderTimeline();syncPlayback();setTimeout(onPreviewTimeUpdate,0);
  }
  function highlightCue(idx){document.querySelectorAll('[data-cue]').forEach(c=>c.classList.toggle('active',Number(c.dataset.cue)===idx));document.querySelectorAll('.timeline-clip').forEach(c=>c.classList.toggle('active',Number(c.dataset.cueIndex)===idx));}
  function timelineTime(sec,millis=false){
    const label=timeLabel(sec);return millis?`${label},${String(Math.floor((sec%1)*1000+.001)).padStart(3,'0')}`:label;
  }
  function seekTimeline(time,center=false){
    timelineCursor=Math.max(0,Math.min(timelineDuration,time));const player=$('previewVideoPlayer');
    if(player.getAttribute('src'))player.currentTime=timelineCursor;
    selectedCue=timelineRows.findIndex(row=>timelineCursor>=row.start&&timelineCursor<row.end);highlightCue(selectedCue);
    if(center&&timelineView){$('timelineScroll').scrollLeft=TimelineMath.scrollForAnchor(timelineView,timelineCursor,timelineView.width/2);paintTimeline();}
    syncPlayback();
  }
  function setTimelineZoom(value,anchorTime=null,anchorPixel=null){
    const scroll=$('timelineScroll'),old=timelineView||TimelineMath.geometry(timelineDuration,scroll.clientWidth,timelineZoom,scroll.scrollLeft);
    if(anchorTime===null){const cursor=timelineCursor;anchorTime=cursor>=old.start&&cursor<=old.end?cursor:(old.start+old.end)/2;}
    if(anchorPixel===null)anchorPixel=Math.max(0,Math.min(old.width,anchorTime*old.pixelsPerSecond-old.scrollLeft));
    timelineZoom=Math.max(0,Math.min(100,value));$('timelineZoom').value=timelineZoom;
    const view=TimelineMath.geometry(timelineDuration,scroll.clientWidth,timelineZoom);
    $('timelineCanvas').style.width=`${view.totalWidth}px`;
    scroll.scrollLeft=TimelineMath.scrollForAnchor(view,anchorTime,anchorPixel);paintTimeline();
  }
  function scheduleTimelinePaint(){if(timelineFrame)return;timelineFrame=requestAnimationFrame(()=>{timelineFrame=0;paintTimeline();});}
  function renderTimeline(){
    if(!$('timelineCanvas'))return;
    const duration=$('previewVideoPlayer').duration;
    timelineRows=srtRowsData.map((row,index)=>({index,start:Math.max(0,parseSrtTimeToSec(row.start)||0),end:Math.max(0,parseSrtTimeToSec(row.end)||0),text:row.vi_text||`Câu ${index+1}`}));
    timelineDuration=Number.isFinite(duration)&&duration>0?duration:Math.max(30,...timelineRows.map(r=>r.end));
    const view=TimelineMath.geometry(timelineDuration,$('timelineScroll').clientWidth,timelineZoom,$('timelineScroll').scrollLeft);
    $('timelineCanvas').style.width=`${view.totalWidth}px`;paintTimeline();syncPlayback();
  }
  function paintTimeline(){
    const scroll=$('timelineScroll');if(!scroll||!scroll.clientWidth)return;
    timelineView=TimelineMath.geometry(timelineDuration,scroll.clientWidth,timelineZoom,scroll.scrollLeft);
    const view=timelineView,ticks=TimelineMath.ticks(view),ruler=$('timelineRuler');ruler.replaceChildren();
    for(const tick of ticks.items){const label=node('span','',timelineTime(tick.time,ticks.step<1));label.style.left=`${tick.x}px`;if(tick.time===view.duration)label.classList.add('timeline-end-tick');ruler.append(label);}
    $('timelineCanvas').style.backgroundSize=`${ticks.step*view.pixelsPerSecond}px 100%`;
    const track=$('subtitleTrack');track.replaceChildren();
    for(const row of TimelineMath.visibleClips(timelineRows,view)){
      const left=row.start*view.pixelsPerSecond,width=Math.max(.5,(Math.min(view.duration,row.end)-row.start)*view.pixelsPerSecond);
      const clip=node('button','timeline-clip'+(width<20?' condensed':'')+(row.index===selectedCue?' active':''),width>=20?row.text:'');
      clip.id=`timeline-cue-${row.index}`;clip.dataset.cueIndex=row.index;clip.style.left=`${left}px`;clip.style.width=`${width}px`;
      clip.title=`Câu ${row.index+1} · ${timelineTime(row.start,true)} → ${timelineTime(row.end,true)} · ${row.text}`;clip.setAttribute('aria-label',`Tua tới câu ${row.index+1}`);
      clip.onclick=()=>{seekTimeline(row.start);const card=document.querySelector(`[data-cue="${row.index}"]`);card?.scrollIntoView({block:'nearest',behavior:'smooth'});};track.append(clip);
    }
    $('timelineScaleLabel').textContent=`${timelineTime(view.start)} – ${timelineTime(view.end)} · 1 vạch ${ticks.step<60?`${Number(ticks.step.toFixed(3))} giây`:ticks.step<3600?`${ticks.step/60} phút`:`${ticks.step/3600} giờ`}`;
    $('timelineZoom').setAttribute('aria-valuetext',`Hiển thị ${view.span.toFixed(1)} giây`);
    const spanSelect=$('timelineSpan');spanSelect.value=timelineZoom===0?'all':Math.abs(view.span-600)<1?'600':Math.abs(view.span-60)<1?'60':Math.abs(view.span-10)<.5?'10':'custom';
    paintWaveforms();clearTimeout(waveTimer);waveTimer=setTimeout(loadVisibleWaveforms,200);syncPlayback();
  }
  function paintWaveforms(){
    if(!timelineView)return;
    for(const id of ['originalWaveTrack','narrationWaveTrack']){
      const host=$(id),record=waveData[id],path=id==='originalWaveTrack'?currentPreviewLoadedPath||srtTargetPath:typeof currentLoadedMp3Path==='string'?currentLoadedMp3Path:'';
      host.replaceChildren();const view=timelineView;
      if(!record||record.path!==path){const hint=node('span','',path?'Đang đọc sóng âm…':id==='originalWaveTrack'?'Chọn video để hiển thị âm thanh gốc':'Chưa có MP3 thuyết minh');hint.style.left=`${view.scrollLeft}px`;host.append(hint);continue;}
      if(record.error||!record.data.peaks.length){const hint=node('span','',record.error?'Không đọc được sóng âm của đoạn này.':'Không có kênh âm thanh');hint.style.left=`${view.scrollLeft}px`;host.append(hint);continue;}
      const data=record.data,svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${view.width} 44`);svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-label','Sóng âm từ file đang chọn');svg.style.left=`${view.scrollLeft}px`;svg.style.width=`${view.width}px`;
      const wave=document.createElementNS(svg.namespaceURI,'path'),maxPeak=Math.max(.001,...data.peaks),commands=[];
      data.peaks.forEach((value,i)=>{const time=record.start+(data.duration||view.duration)*i/data.peaks.length,x=(time-view.start)*view.pixelsPerSecond;if(x< -2||x>view.width+2)return;const height=Math.max(.4,Math.sqrt(value/maxPeak)*20);commands.push(`M${x.toFixed(2)},${(22-height).toFixed(2)}V${(22+height).toFixed(2)}`);});
      wave.setAttribute('d',commands.join(''));svg.append(wave);host.append(svg);
    }
  }
  async function loadVisibleWaveforms(){
    if(!timelineView||activePage!=='editor')return;const view=timelineView;
    const span=Math.max(1,Math.ceil(view.span)),start=view.ratio<=1.01?0:Math.max(0,Math.floor(view.start/span)*span-span),duration=Math.min(timelineDuration-start,span*3);
    await Promise.all(['originalWaveTrack','narrationWaveTrack'].map(async id=>{
      const path=id==='originalWaveTrack'?currentPreviewLoadedPath||srtTargetPath:typeof currentLoadedMp3Path==='string'?currentLoadedMp3Path:'';
      if(!path){waveRequests[id]?.controller.abort();delete waveRequests[id];return;}
      const range=view.ratio<=1.01?'':`&start=${start}&duration=${duration}`,key=path+range;
      if(waveRequests[id]?.key===key||waveData[id]?.key===key)return;
      waveRequests[id]?.controller.abort();const controller=new AbortController();waveRequests[id]={key,controller};
      try{let data=waveformCache.get(key);if(!data){const response=await fetch(`/api/waveform?path=${encodeURIComponent(path)}${range}`,{signal:controller.signal});if(!response.ok)throw new Error();data=await response.json();waveformCache.set(key,data);if(waveformCache.size>24)waveformCache.delete(waveformCache.keys().next().value);}
        if(waveRequests[id]?.key!==key)return;waveData[id]={key,path,start:range?start:0,data};paintWaveforms();
      }catch(error){if(error.name==='AbortError'||waveRequests[id]?.key!==key)return;waveData[id]={key,path,error:true};paintWaveforms();}
      finally{if(waveRequests[id]?.key===key)delete waveRequests[id];}
    }));
  }
  function syncPlayback(){
    const player=$('previewVideoPlayer');if(!player||!$('editorTime'))return;const loaded=!!player.getAttribute('src');$('editorPreviewEmpty').hidden=loaded;$('previewPlayerWrap').hidden=!loaded;
    if(loaded)timelineCursor=player.currentTime||0;
    $('editorTime').textContent=`${timelineTime(timelineCursor,true)} / ${timeLabel(Number.isFinite(player.duration)?player.duration:timelineDuration)}`;$('editorPlay').innerHTML=player.paused?icon('play'):'Ⅱ';
    const source=currentPreviewLoadedPath||srtTargetPath;$('editorDocumentName').textContent=source?source.split(/[\\/]/).pop():'Chọn một phần để bắt đầu';
    $('timelinePlayhead').style.left=`${Math.min(timelineDuration,timelineCursor)*(timelineView?.pixelsPerSecond||1)}px`;
    if(!player.paused){const idx=timelineRows.findIndex(r=>timelineCursor>=r.start&&timelineCursor<r.end);if(idx!==selectedCue){selectedCue=idx;highlightCue(idx);}if(timelineView&&(timelineCursor>timelineView.end||timelineCursor<timelineView.start))$('timelineScroll').scrollLeft=TimelineMath.scrollForAnchor(timelineView,timelineCursor,timelineView.width*.2);}
  }
  function navigate(page,project=null) {
    const hash=`#/${page}${project!==null?'?project='+encodeURIComponent(project):''}`;
    if(location.hash===hash)route();else location.hash=hash;
  }
  function route() {
    const [page,params='']=(location.hash.slice(2)||'operate').split('?');
    activePage=labels[page]?page:'operate';const nextProject=activePage==='library'?new URLSearchParams(params).get('project'):activeProject;
    if(activePage==='library'&&nextProject!==activeProject){selectedOutputPaths.clear();query='';$('librarySearch').value='';filter='all';$('libraryFilter').value='all';}
    activeProject=nextProject;
    document.querySelectorAll('[data-page]').forEach(p=>p.classList.toggle('active',p.dataset.page===activePage));
    document.querySelectorAll('[data-page-nav]').forEach(b=>{const active=b.dataset.pageNav===activePage;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    $('studioCrumb').textContent=labels[activePage];document.body.classList.remove('mobile-nav-open');renderLibrary();window.scrollTo(0,0);
    if(activePage==='library')refresh();if(activePage==='editor'){renderTimeline();updateCapcutSubPreviewStyle();}
  }
  async function refresh(force=false) {
    if(loading)return;loading=true;
    try{const res=await fetch('/api/library');if(!res.ok)throw new Error('Không đọc được kho đầu ra. Hãy mở lại tool để dùng giao diện mới.');const data=await res.json();const sig=JSON.stringify(data);libraryError='';if(force||sig!==librarySignature){librarySignature=sig;library=data;renderLibrary();}if(force)toast('Đã cập nhật dữ liệu từ thư mục output/.');}
    catch(e){libraryError=e.message;if(force)toast(e.message,true);renderLibrary();}
    finally{loading=false;}
  }
  function stateLabel(value){return {complete:'Đủ 3 tệp',partial:'Chưa đầy đủ',running:'Đang xử lý',error:'Cần thử lại',stopped:'Đã dừng',empty:'Chưa có tệp'}[value]||'Chưa đầy đủ';}
  function matchesStatus(part) {return filter==='all'||(filter==='pending'?['partial','empty','stopped'].includes(part.status):part.status===filter);}
  function visibleParts(project){return project.parts.filter(p=>matchesStatus(p)&&`${p.name} ${p.file_name}`.toLocaleLowerCase('vi').includes(query.toLocaleLowerCase('vi'))).sort((a,b)=>sort==='name'?a.chunk_index-b.chunk_index:b.modified_at-a.modified_at||a.chunk_index-b.chunk_index);}
  function renderLibrary() {
    if(!$('libraryContent'))return;
    $('navLibraryCount').textContent=library.summary.projects;
    for(const id of ['projects','parts','complete'])$(`libraryStat-${id}`).textContent=library.summary[id].toLocaleString('vi-VN');$('libraryStat-size').textContent=bytes(library.summary.size_bytes);
    const tree=$('sidebarProjectTree');tree.replaceChildren();
    if(!library.projects.length)tree.append(node('div','sidebar-empty','Các bộ đã xuất sẽ xuất hiện tại đây.'));
    library.projects.slice(0,10).forEach(p=>{const b=button(p.name,'project-nav'+(activePage==='library'&&activeProject===p.id?' active':''),()=>navigate('library',p.id),'folder');b.title=p.name;const text=b.lastChild;b.removeChild(text);b.append(node('span','',p.name),node('small','nav-count',String(p.part_count)));tree.append(b);});
    const p=library.projects.find(p=>p.id===activeProject);
    $('libraryViewModes').hidden=false;$('libraryBack').hidden=!activeProject;$('libraryBreadcrumb').hidden=!activeProject;
    $('libraryBulkHost').hidden=!p||!p.parts.length;
    document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);b.setAttribute('aria-pressed',String(b.dataset.view===view));});
    const content=$('libraryContent');content.replaceChildren();
    if(libraryError){empty(content,'Kho đầu ra chưa kết nối',libraryError,'Thử lại',()=>refresh(true),'refresh');return;}
    if(activeProject&&!p){empty(content,'Không tìm thấy bộ này','Thư mục có thể đã được đổi tên hoặc di chuyển.','Về kho đầu ra',()=>navigate('library'),'folder');return;}
    if(p){
      const crumb=$('libraryBreadcrumb');crumb.replaceChildren(button('Kho đầu ra','',()=>navigate('library')),iconNode('chevron'),node('strong','',p.name));
      $('librarySectionTitle').textContent='Các phần trong bộ';$('librarySearch').placeholder='Tìm phần trong bộ này…';
      currentFinishedOutputs=p.parts.filter(p=>p.path);
      const known=new Set(currentFinishedOutputs.map(p=>p.path));selectedOutputPaths=new Set([...selectedOutputPaths].filter(path=>known.has(path)));
      $('exportedSelectionLabel').textContent=`Đã chọn ${selectedOutputPaths.size}/${currentFinishedOutputs.length} phần`;
      const parts=visibleParts(p);if(!parts.length)empty(content,p.parts.length?'Không có phần phù hợp':'Bộ này chưa có phần nào',p.parts.length?'Đổi từ khóa hoặc bộ lọc để xem các phần khác.':'Các phần sẽ xuất hiện khi tác vụ bắt đầu trả video vào thư mục bộ.',p.parts.length?'Xóa bộ lọc':'Tới vận hành',()=>p.parts.length?resetFilters():navigate('operate'),'file');else renderParts(content,parts);
      $('libraryFooterText').textContent=`${parts.length}/${p.part_count} phần · ${bytes(p.size_bytes)} · ${p.name}`;
    }else{
      currentFinishedOutputs=[];$('librarySectionTitle').textContent='Các bộ trong kho';$('librarySearch').placeholder='Tìm bộ truyện, dự án…';
      const projects=library.projects.filter(p=>`${p.name} ${p.parts.map(part=>part.name+' '+part.file_name).join(' ')}`.toLocaleLowerCase('vi').includes(query.toLocaleLowerCase('vi'))&&(filter==='all'||p.parts.some(matchesStatus))).sort((a,b)=>sort==='name'?a.name.localeCompare(b.name,'vi',{numeric:true}):b.modified_at-a.modified_at);
      if(!projects.length)empty(content,library.projects.length?'Chưa tìm thấy bộ phù hợp':'Kho đầu ra đang trống',library.projects.length?'Thử từ khóa khác hoặc bỏ bộ lọc hiện tại.':'Bắt đầu từ một video. Mỗi bộ và các phần hoàn tất sẽ được sắp xếp tự động tại đây.',library.projects.length?'Xóa bộ lọc':'Tạo tác vụ đầu tiên',()=>library.projects.length?resetFilters():navigate('operate'),'folder');
      else{const grid=node('div',view==='grid'?'project-grid':'project-list-view');projects.forEach(p=>grid.append(projectCard(p)));content.append(grid);}
      $('libraryFooterText').textContent=`${projects.length} bộ · Dữ liệu từ thư mục output/`;
    }
    updateBatchButtons();
  }
  function resetFilters(){query='';filter='all';$('librarySearch').value='';$('libraryFilter').value='all';renderLibrary();}
  function empty(parent,title,desc,action,callback,glyph){const box=node('div','library-empty');box.append(iconNode(glyph,'empty-art'),node('h3','',title),node('p','',desc));if(action)box.append(button(action,'btn btn-primary',callback,glyph==='refresh'?'refresh':'plus'));parent.append(box);}
  function projectCard(p){const b=node('button','project-card');b.type='button';b.onclick=()=>navigate('library',p.id);b.title=`Mở bộ ${p.name}`;const top=node('div','project-card-top');const video=p.parts.find(part=>part.path);if(video){const thumb=node('video','project-thumbnail');thumb.src=`/api/video-stream?path=${encodeURIComponent(video.path)}#t=0.1`;thumb.preload='metadata';thumb.muted=true;thumb.setAttribute('aria-hidden','true');top.append(thumb);}top.append(iconNode('folder','folder-glyph'),node('span','project-card-count',`${p.part_count} phần`));const name=node('div');name.append(node('h3','',p.name),node('p','',`${p.complete_count}/${p.part_count} phần đủ video, SRT, MP3`));const progress=node('div','mini-progress');const fill=node('span');fill.style.width=`${p.part_count?p.complete_count/p.part_count*100:0}%`;progress.append(fill);const footer=node('div','project-card-footer');footer.append(node('span','',date(p.modified_at)),node('span','',bytes(p.size_bytes)));b.append(top,name,progress,footer);return b;}
  function renderParts(parent,parts){
    if(view==='grid'){renderPartCards(parent,parts);return;}
    const wrap=node('div','library-table-wrap'),table=node('table','library-table'),head=node('thead'),tr=node('tr');
    const select=node('input');select.type='checkbox';select.setAttribute('aria-label','Chọn tất cả phần đang hiển thị');
    const selectable=parts.filter(p=>p.path),count=selectable.filter(p=>selectedOutputPaths.has(p.path)).length;select.checked=selectable.length>0&&count===selectable.length;select.indeterminate=count>0&&count<selectable.length;select.disabled=!selectable.length;select.onchange=()=>selectAll(select.checked);
    const cell=node('th');cell.append(select);tr.append(cell);['Tên phần','Các tệp','Trạng thái','Dung lượng',''].forEach(t=>tr.append(node('th','',t)));head.append(tr);table.append(head);
    const body=node('tbody');parts.forEach(p=>{
      const row=node('tr'),checkCell=node('td'),check=node('input');check.type='checkbox';check.disabled=!p.path;check.checked=selectedOutputPaths.has(p.path);check.setAttribute('aria-label',`Chọn ${p.name}`);check.onchange=()=>{if(check.checked)selectedOutputPaths.add(p.path);else selectedOutputPaths.delete(p.path);renderLibrary();};checkCell.append(check);row.append(checkCell);
      const nameCell=node('td'),name=node('div','library-part-name'),text=node('div');text.append(node('strong','',p.name),node('small','',p.file_name));name.append(iconNode('file','part-file-icon'),text);nameCell.append(name);row.append(nameCell);
      const files=node('td'),tags=node('div','file-tags');[['VIDEO',p.path],['SRT',p.srt_path],['MP3',p.audio_vi]].forEach(([label,path])=>{const tag=node(path?'a':'span','file-tag'+(path?'':' missing'),label);if(path){tag.href=`/api/video-stream?path=${encodeURIComponent(path)}`;tag.download=path.split(/[\\/]/).pop();tag.title=`Tải ${label}`;}tags.append(tag);});files.append(tags);row.append(files);
      const statusCell=node('td');statusCell.append(node('span',`state-tag ${p.status}`,stateLabel(p.status)));if(p.error)statusCell.append(node('div','library-error-message',p.error));row.append(statusCell);
      const size=node('td','',bytes(p.size_bytes));if(p.duration_human)size.append(node('small','',` · ${p.duration_human}`));row.append(size);
      const actions=node('td'),buttons=node('div','row-actions');if(p.path){const preview=button('','icon-button',()=>previewSpecificVideo(p.path),'play');preview.title=`Mở ${p.name} trong bàn biên tập`;preview.setAttribute('aria-label',preview.title);buttons.append(preview);}const folder=button('','icon-button',()=>openOutputFolder(p.folder),'folder');folder.title='Mở thư mục phần trên máy';folder.setAttribute('aria-label',folder.title);buttons.append(folder);actions.append(buttons);row.append(actions);body.append(row);
    });table.append(body);wrap.append(table);parent.append(wrap);
  }
  function renderPartCards(parent,parts){
    const grid=node('div','part-grid');parts.forEach(p=>{
      const card=node('article','part-card'+(selectedOutputPaths.has(p.path)?' selected':''));
      const media=node('div','part-card-media');if(p.path){const video=node('video');video.src=`/api/video-stream?path=${encodeURIComponent(p.path)}#t=0.1`;video.preload='metadata';video.muted=true;video.setAttribute('aria-hidden','true');media.append(video);}else media.append(iconNode('file','part-card-no-video'));
      const check=node('input','part-card-check');check.type='checkbox';check.checked=selectedOutputPaths.has(p.path);check.disabled=!p.path;check.setAttribute('aria-label',`Chọn ${p.name}`);check.onchange=()=>{if(check.checked)selectedOutputPaths.add(p.path);else selectedOutputPaths.delete(p.path);card.classList.toggle('selected',check.checked);$('exportedSelectionLabel').textContent=`Đã chọn ${selectedOutputPaths.size}/${currentFinishedOutputs.length} phần`;updateBatchButtons();};media.append(check);
      media.append(node('span','part-card-index',String(p.chunk_index).padStart(2,'0')));if(p.duration_human)media.append(node('span','part-card-duration',p.duration_human));card.append(media);
      const body=node('div','part-card-body');body.append(node('h3','',p.name),node('p','part-card-filename',p.file_name));
      const tags=node('div','file-tags');[['Video',p.path],['SRT',p.srt_path],['MP3',p.audio_vi]].forEach(([label,path])=>{const tag=node(path?'a':'span','file-tag'+(path?'':' missing'),label);if(path){tag.href=`/api/video-stream?path=${encodeURIComponent(path)}`;tag.download=path.split(/[\\/]/).pop();tag.title=`Tải ${label}`;}tags.append(tag);});body.append(tags);
      const meta=node('div','part-card-meta');meta.append(node('span',`state-tag ${p.status}`,stateLabel(p.status)),node('span','',bytes(p.size_bytes)));body.append(meta);
      if(p.error)body.append(node('p','library-error-message',p.error));
      const actions=node('div','part-card-actions');if(p.path)actions.append(button('Mở Studio','btn btn-primary',()=>previewSpecificVideo(p.path),'play'));const folder=button('','icon-button',()=>openOutputFolder(p.folder),'folder');folder.title=`Mở thư mục ${p.name}`;folder.setAttribute('aria-label',folder.title);actions.append(folder);body.append(actions);card.append(body);grid.append(card);
    });parent.append(grid);
  }
  function selectAll(all){const p=library.projects.find(p=>p.id===activeProject);if(!p)return;visibleParts(p).forEach(p=>{if(p.path){if(all)selectedOutputPaths.add(p.path);else selectedOutputPaths.delete(p.path);}});renderLibrary();}
  function updateBatchButtons(){document.querySelectorAll('[data-workflow-action]').forEach(b=>b.disabled=!!status.is_running||!selectedOutputPaths.size);}
  function updatePlan(plan){if(!plan)return;$('operateSourceCount').textContent=`${(plan.items||[]).length} video nguồn`;$('operateSelectedCount').textContent=`${selectedChunkSet.size} / ${(plan.chunks||[]).length} phần`;updateMode();}
  function updateMode(){const value=$('workflowModeSelect')?.value;if($('startBtn'))$('startBtn').textContent=selectedChunkSet.size?`Bắt đầu xử lý ${selectedChunkSet.size} phần`:'Bắt đầu quy trình';$('operateWorkflow').textContent={full:'Video · SRT · MP3',srt:'Video · SRT',video:'Chỉ video'}[value]||'Video · SRT · MP3';}
  function updateStatus(st){
    status=st;const running=!!st.is_running,failed=!running&&!!st.error_message;
    $('topbarRun').className=`topbar-run${running?' running':failed?' error':''}`;$('topbarRunText').textContent=running?`Đang xử lý · ${Math.round(st.overall_pct||0)}%`:failed?'Cần kiểm tra':'Sẵn sàng';
    $('navRunCount').hidden=!running;$('navRunCount').textContent=`${Math.round(st.overall_pct||0)}%`;$('runStopButton').hidden=!running;
    $('runOverviewTitle').textContent=running?`Đang xử lý phần ${st.current_chunk_idx||1}`:failed?'Một tác vụ cần kiểm tra':st.overall_pct===100?'Tác vụ đã kết thúc':'Sẵn sàng cho tác vụ mới';
    $('runOverviewHint').textContent=running?plain(st.status_phase):failed?plain(st.error_message):st.overall_pct===100?'Mở kho đầu ra để xem kết quả và chạy tiếp các phần còn thiếu.':'Chọn video và các phần cần xử lý trong trang Vận hành.';
    let step=0;const phase=st.status_phase||'';if(/Whisper|nhận diện/.test(phase))step=1;else if(/dịch|SRT/.test(phase))step=2;if(/MP3|TTS|giọng|thuyết minh/i.test(phase))step=3;
    document.querySelectorAll('[data-stage]').forEach(e=>e.classList.toggle('active',running&&Number(e.dataset.stage)===step));updateBatchButtons();
    const disk=$('diskBadge');if(disk)$('sidebarDiskText').textContent=plain(disk.textContent);
  }
  function updateLiveOutputs(outputs){const sig=JSON.stringify(outputs);if(sig!==lastOutputs){lastOutputs=sig;refresh();}}
  return {mount,navigate,refresh,selectAll,updatePlan,updateMode,updateStatus,updateLiveOutputs,toast,renderEditor};
})();
