import test from 'node:test';
import assert from 'node:assert/strict';
import { heatColor, heatTextColor } from '../../lib/chart.ts';
import { setColorMode } from '../../lib/colorPreference.ts';
import { setThemePreference } from '../../lib/themePreference.ts';

function luminance(channels) {
  const linear=channels.map(v=>v/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
  return linear[0]*.2126+linear[1]*.7152+linear[2]*.0722;
}
function contrast(background,foreground) {
  const bg=luminance(background.match(/\d+/g).map(Number));
  const fg=luminance([1,3,5].map(offset=>parseInt(foreground.slice(offset,offset+2),16)));
  return (Math.max(bg,fg)+.05)/(Math.min(bg,fg)+.05);
}

test('all heat tile colors have readable text in both themes and both price modes',()=>{
  for(const theme of ['light','dark']) {
    setThemePreference(theme);
    for(const mode of ['asian','western']) {
      setColorMode(mode);
      for(let tick=-300;tick<=300;tick++) {
        const bg=heatColor(tick/100), fg=heatTextColor(bg);
        assert.ok(contrast(bg,fg)>=4.5,`${theme}/${mode}/${tick}: ${bg} ${fg}`);
      }
    }
  }
  setThemePreference('light');setColorMode('asian');
});

test('zero-return heat tiles retain dark ink after switching to dark appearance',()=>{
  setThemePreference('dark');
  assert.equal(heatTextColor(heatColor(0)),'#111111');
  setThemePreference('light');
});
