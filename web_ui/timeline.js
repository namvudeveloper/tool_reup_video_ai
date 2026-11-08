/* Shared, bounded timeline geometry. Zoom 0 fits the entire source; 100 shows
   about five seconds. Rendering uses only the visible interval. */
(function(root){
  function clamp(value,min,max){return Math.min(max,Math.max(min,value));}
  function geometry(duration,width,zoom=0,scrollLeft=0){
    duration=Math.max(.001,Number(duration)||30);width=Math.max(1,Number(width)||1);
    const maxRatio=Math.max(1,Math.min(duration/5,8000000/width));
    const ratio=Math.pow(maxRatio,clamp(zoom,0,100)/100);
    const totalWidth=Math.max(width,width*ratio),pixelsPerSecond=totalWidth/duration;
    scrollLeft=clamp(scrollLeft,0,Math.max(0,totalWidth-width));
    return {duration,width,ratio,totalWidth,pixelsPerSecond,scrollLeft,
      start:scrollLeft/pixelsPerSecond,end:Math.min(duration,(scrollLeft+width)/pixelsPerSecond),span:width/pixelsPerSecond};
  }
  function niceStep(seconds){
    const standard=[.01,.02,.05,.1,.2,.5,1,2,5,10,15,30,60,120,300,600,900,1800,3600,7200,14400,28800,86400];
    const match=standard.find(step=>step>=seconds);if(match)return match;
    const base=10**Math.floor(Math.log10(Math.max(.001,seconds)));
    return [1,2,5,10].map(n=>n*base).find(n=>n>=seconds)||base*10;
  }
  function ticks(view){
    const step=niceStep(90/view.pixelsPerSecond),result=[];
    const first=Math.max(0,Math.floor(view.start/step));
    for(let i=first;i*step<=view.end+step*.01;i++){
      const time=i*step;if(time>view.duration)break;
      result.push({time,x:time*view.pixelsPerSecond});
    }
    if(view.end>=view.duration-.001&&!result.some(t=>Math.abs(t.time-view.duration)<step*.05))result.push({time:view.duration,x:view.totalWidth});
    return {step,items:result};
  }
  function zoomForSpan(duration,width,span){
    const maxRatio=geometry(duration,width,100).ratio;
    return maxRatio<=1?0:clamp(Math.log(Math.max(1,duration/span))/Math.log(maxRatio)*100,0,100);
  }
  function scrollForAnchor(view,time,anchorPixel){return clamp(time*view.pixelsPerSecond-anchorPixel,0,view.totalWidth-view.width);}
  function visibleClips(rows,view){return rows.filter(row=>row.end>=view.start&&row.start<=view.end);}
  const api={geometry,ticks,niceStep,zoomForSpan,scrollForAnchor,visibleClips};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.TimelineMath=api;
})(typeof window==='object'?window:this);
