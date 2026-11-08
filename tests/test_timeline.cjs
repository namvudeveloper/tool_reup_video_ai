const test=require('node:test');
const assert=require('node:assert/strict');
const Timeline=require('../web_ui/timeline.js');

test('eight hours can fit and zoom to five seconds without millions of ruler nodes',()=>{
 const full=Timeline.geometry(8*3600,900,0);
 assert.equal(full.start,0);assert.equal(full.end,28800);assert.equal(full.totalWidth,900);
 const zoom=Timeline.geometry(28800,900,100);
 assert.ok(Math.abs(zoom.span-5)<1e-8);assert.ok(zoom.totalWidth<=8000000);
 const atFourHours=Timeline.geometry(28800,900,100,14400*zoom.pixelsPerSecond);
 const ticks=Timeline.ticks(atFourHours);
 assert.ok(ticks.items.length<25);assert.ok(ticks.step<=1);
 assert.ok(ticks.items.every(t=>t.time>=atFourHours.start-ticks.step&&t.time<=atFourHours.end));
});

test('zoom keeps the same time under the anchor and supports useful duration presets',()=>{
 for(const span of [600,60,10]){
  const zoom=Timeline.zoomForSpan(28800,960,span),view=Timeline.geometry(28800,960,zoom);
  assert.ok(Math.abs(view.span-span)<1e-7);
  const scroll=Timeline.scrollForAnchor(view,14400,300);
  assert.ok(Math.abs((scroll+300)/view.pixelsPerSecond-14400)<1e-7);
 }
});

test('only visible subtitle clips are returned for a large subtitle set',()=>{
 const rows=Array.from({length:14400},(_,i)=>({start:i*2,end:i*2+1.8}));
 const view=Timeline.geometry(28800,1000,100,1000/5*14400);
 const visible=Timeline.visibleClips(rows,view);
 assert.ok(visible.length<=4);assert.ok(visible.every(row=>row.end>=view.start&&row.start<=view.end));
});

test('fit and maximum zoom remain bounded at the start and end',()=>{
 const view=Timeline.geometry(28800,900,100,Infinity);
 assert.equal(view.end,28800);assert.ok(view.start>=0);
 assert.equal(Timeline.scrollForAnchor(view,28800,0),view.totalWidth-view.width);
 assert.equal(Timeline.geometry(28800,900,0,100000).scrollLeft,0);
 assert.equal(Timeline.ticks(Timeline.geometry(28800,900,0)).step,3600);
});
