/** 同一只股票的多条雷达信号合并成一张卡：不丢信号、顺序稳定、展示优先级最高的一条。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { groupSignalsByStock } from '../src/components/radar/groupSignals.ts';

const event = (event_id, canonical_code, alert_priority) => ({ event_id, canonical_code, alert_priority });

test('按股票分组，组的先后是该股票第一次出现的位置', () => {
  const groups = groupSignalsByStock([
    event('a1', '45020', 66), event('b1', '23310', 65), event('a2', '45020', 60), event('c1', '49720', 63), event('b2', '23310', 64),
  ]);
  assert.deepEqual(groups.map((group) => group.key), ['45020', '23310', '49720']);
  assert.deepEqual(groups.map((group) => group.primary.event_id), ['a1', 'b1', 'c1']);
  assert.deepEqual(groups[0].others.map((item) => item.event_id), ['a2']);
  assert.deepEqual(groups[2].others, []);
});

test('每组展示优先级最高的一条，同分时保留先出现的', () => {
  const [group] = groupSignalsByStock([event('low', '64600', 50), event('high', '64600', 57), event('tie', '64600', 57)]);
  assert.equal(group.primary.event_id, 'high');
  assert.deepEqual(group.others.map((item) => item.event_id), ['low', 'tie']);
});

test('优先级缺失或不是有限数时排在最后，全部缺失时取第一条', () => {
  const [mixed] = groupSignalsByStock([event('none', '90090', null), event('nan', '90090', Number.NaN), event('scored', '90090', 1)]);
  assert.equal(mixed.primary.event_id, 'scored');
  const [empty] = groupSignalsByStock([event('first', '82550', null), event('second', '82550', null)]);
  assert.equal(empty.primary.event_id, 'first');
});

test('合并前后信号总数不变，也不改动输入', () => {
  const input = Array.from({ length: 200 }, (_, index) => event(`e${index}`, String(10000 + (index % 59)), (index * 37) % 100));
  const snapshot = JSON.stringify(input);
  const groups = groupSignalsByStock(input);
  assert.equal(groups.length, 59);
  const ids = groups.flatMap((group) => [group.primary, ...group.others]).map((item) => item.event_id).sort();
  assert.deepEqual(ids, input.map((item) => item.event_id).sort());
  assert.equal(JSON.stringify(input), snapshot);
  assert.deepEqual(groupSignalsByStock([]), []);
});
