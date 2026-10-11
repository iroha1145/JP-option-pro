import test from 'node:test';
import assert from 'node:assert/strict';
import { setThemePreference } from '../../../lib/themePreference.ts';
import { setColorMode, directionColors, subscribeColorMode } from '../../../lib/colorPreference.ts';
import { CH, glassTooltip, insightLineSeries } from '../../../lib/chart.ts';
import { drawingPaint, drawingSurface } from './drawingAppearance.ts';
import { renderPatternInk } from './linePresentation.ts';
import { insideZoom } from './zoom.ts';

test.afterEach(() => { setThemePreference('light'); setColorMode('asian'); });

test('canvas palette, tooltip, endpoints and Asian candles update in both appearances', () => {
  setColorMode('asian');
  setThemePreference('light');
  const light = { grid: CH.lineChart, tooltip: glassTooltip(), ring: insightLineSeries({data:[1,2]}).markPoint.itemStyle.borderColor };
  assert.equal(directionColors().up600, '#E5484D');
  setThemePreference('dark');
  assert.equal(directionColors().up600, '#FF8A80');
  assert.equal(directionColors().down600, '#62D0A5');
  assert.notEqual(CH.lineChart, light.grid);
  assert.notEqual(glassTooltip().backgroundColor, light.tooltip.backgroundColor);
  assert.notEqual(insightLineSeries({data:[1,2]}).markPoint.itemStyle.borderColor, light.ring);
  setColorMode('western');
  assert.equal(directionColors().up600, '#62D0A5');
  assert.equal(directionColors().down600, '#FF8A80');
});

test('appearance changes notify chart color subscribers', () => {
  let notifications=0;
  const stop=subscribeColorMode(() => notifications++);
  setThemePreference('dark');
  assert.equal(notifications,1);
  stop();
});

test('drawing recoloring preserves anchors and saved ink and darkens label surfaces', () => {
  const pattern={id:'fixture',kind:'support_trend',status:'forming',confidence:90,label:'support'};
  const geometry={segments:[{a:{x:0,y:100},b:{x:5,y:105}}],fill:null};
  const original=structuredClone(geometry);
  const context={xMin:0,xMax:10,yMin:90,yMax:120};
  setThemePreference('light');
  const light=renderPatternInk(pattern,geometry,context);
  setThemePreference('dark');
  const dark=renderPatternInk(pattern,geometry,context);
  assert.deepEqual(geometry,original);
  assert.deepEqual(dark.lines.map(row=>row.map(point=>point.coord)),light.lines.map(row=>row.map(point=>point.coord)));
  assert.notEqual(dark.lines[0][0].lineStyle.color,light.lines[0][0].lineStyle.color);
  assert.equal(drawingSurface(.97),'rgba(22,22,23,0.97)');
  assert.equal(drawingPaint('#123456'),'#123456');
});

test('theme repaint preserves the chosen historical zoom window and all synchronized axes', () => {
  const saved={start:20,end:60,pinnedEnd:false};
  setThemePreference('light');
  const light=insideZoom(200,[0,1,2],saved);
  setThemePreference('dark');
  const dark=insideZoom(200,[0,1,2],saved);
  assert.deepEqual(dark.map(row=>[row.startValue,row.endValue,row.xAxisIndex]), light.map(row=>[row.startValue,row.endValue,row.xAxisIndex]));
  assert.notEqual(dark[1].backgroundColor,light[1].backgroundColor);
});
