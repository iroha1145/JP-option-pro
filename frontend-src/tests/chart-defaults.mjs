import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_LAYER_SETTINGS, loadLayerSettings, parseLayerSettings, saveLayerSettings,
  settingsFromPreset, toggleLayer,
} from '../src/components/detail/chart-drawings/analysis/settings.ts';
import { filterOverlays, filterPanes, labelBudget } from '../src/components/detail/chart-drawings/analysis/mapBundle.ts';
import { LAYERS, layersStorageKey } from '../src/components/detail/chart-drawings/analysis/registry.ts';

const panes = ['rsi', 'macd', 'obv', 'clv', 'range_persistence', 'topix_rs'];
const oldDefault = {
  schemaVersion: 2, preset: 'custom',
  enabled: ['ma20', 'swings', 'support_resistance', 'bases', 'auto_patterns', ...panes],
  minShapeQuality: 0.45, onlyActive: false, showInvalidated: false,
  maxPatterns: 8, maxLabels: 10, labelDensity: 0.7,
};
const oldMinimal = {
  schemaVersion: 2, preset: 'minimal', enabled: ['ma20', 'auto_patterns'],
  minShapeQuality: 0.45, onlyActive: true, showInvalidated: false,
  maxPatterns: 3, maxLabels: 6, labelDensity: 0.4,
};
const withoutVersion = ({ schemaVersion, ...settings }) => settings;
const overlay = (id, status='forming', priority=1) => ({
  id, status, kind:'support_trend', shapeQuality:0.8, displayPriority:priority,
});

test('default chart keeps one main pattern, one label and all six indicator choices', () => {
  const settings=loadLayerSettings('new-user',{getItem:()=>null});
  assert.deepEqual(settings.enabled,['ma20','auto_patterns',...panes]);
  const proposals=[overlay('first','forming',10),overlay('second','testing',5),overlay('third','forming',3)];
  const visible=filterOverlays(proposals,settings);
  assert.deepEqual(visible.map(o=>o.id),['first']);
  assert.equal(labelBudget(visible,settings).length,1);
  assert.deepEqual(filterPanes(panes.map(id=>({id})),settings).map(p=>p.id),panes);
});

test('unmodified old defaults and old minimal preset receive the quieter defaults', () => {
  assert.deepEqual(parseLayerSettings(oldDefault),DEFAULT_LAYER_SETTINGS);
  assert.deepEqual(parseLayerSettings({...oldDefault,enabled:[...oldDefault.enabled].reverse()}),DEFAULT_LAYER_SETTINGS);
  assert.deepEqual(parseLayerSettings(oldMinimal),settingsFromPreset('minimal'));
});

for(const [name,change] of [
  ['pattern count',{maxPatterns:5}],
  ['label density',{labelDensity:0.6}],
  ['quality threshold',{minShapeQuality:0.7}],
  ['layer selection',{enabled:oldDefault.enabled.filter(id=>id!=='obv')}],
  ['history selection',{onlyActive:true}],
]) {
  test(`keep existing customized ${name}`,()=>{
    const saved={...oldDefault,...change};
    assert.deepEqual(parseLayerSettings(saved),withoutVersion(saved));
  });
}

test('do not migrate settings just because their preset name is minimal',()=>{
  const saved={...oldMinimal,maxPatterns:7};
  assert.deepEqual(parseLayerSettings(saved),withoutVersion(saved));
});

test('newly saved preferences are stable even when they match the old default',()=>{
  const saved=new Map();
  const storage={getItem:key=>saved.get(key)??null,setItem:(key,value)=>saved.set(key,value)};
  saveLayerSettings('account:example',withoutVersion(oldDefault),storage);
  assert.equal(JSON.parse(saved.get(layersStorageKey('account:example'))).schemaVersion,3);
  assert.deepEqual(loadLayerSettings('account:example',storage),withoutVersion(oldDefault));
  assert.deepEqual(loadLayerSettings('anonymous',storage),DEFAULT_LAYER_SETTINGS);
});

test('v2 explicit quality is preserved and the old v1 quality migration remains unchanged',()=>{
  assert.equal(parseLayerSettings({...oldMinimal,minShapeQuality:0.7}).minShapeQuality,0.7);
  assert.equal(parseLayerSettings({...oldMinimal,schemaVersion:1,minShapeQuality:0.7}).minShapeQuality,0.45);
});

test('current-only mode excludes broken and expired lines; history can still be enabled',()=>{
  const proposals=['forming','testing','triggered','confirmed','retest','broken_up','broken_down','failed','expired','invalidated']
    .map(status=>overlay(status,status));
  const settings={...DEFAULT_LAYER_SETTINGS,maxPatterns:20};
  assert.deepEqual(filterOverlays(proposals,settings).map(o=>o.id),['forming','testing','triggered','confirmed','retest']);
  assert.equal(filterOverlays(proposals,{...settings,onlyActive:false,showInvalidated:true}).length,proposals.length);
});

test('advanced presets and every layer remain available',()=>{
  const all=settingsFromPreset('all');
  assert.deepEqual(all.enabled,LAYERS.map(l=>l.id));
  assert.equal(all.maxPatterns,12);
  assert.equal(settingsFromPreset('structure').maxPatterns,8);
  assert.ok(toggleLayer(DEFAULT_LAYER_SETTINGS,'bases').enabled.includes('bases'));
});
