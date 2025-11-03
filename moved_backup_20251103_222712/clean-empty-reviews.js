// Script to clean empty reviews from KV
// Run with: node clean-empty-reviews.js

const { execSync } = require('child_process');

async function cleanEmptyReviews() {
  try {
    // Get all keys from KV using correct wrangler syntax
    const listCmd = 'wrangler kv key list --namespace-id 2d17bc191bfd41998759f2786e3dd6c3';
    const keysOutput = execSync(listCmd, { encoding: 'utf8' });
    
    // Extract JSON from output (wrangler adds text before JSON)
    const jsonStart = keysOutput.indexOf('[');
    const jsonEnd = keysOutput.lastIndexOf(']') + 1;
    const jsonStr = keysOutput.substring(jsonStart, jsonEnd);
    
    const keys = JSON.parse(jsonStr).map(k => k.name).filter(k => k && k !== 'events:version');

    console.log(`Found ${keys.length} keys`);

    for (const key of keys) {
      try {
        // Get the value
        const getCmd = `wrangler kv key get "${key}" --namespace-id 2d17bc191bfd41998759f2786e3dd6c3`;
        const value = execSync(getCmd, { encoding: 'utf8' });
        
        // Extract JSON from output
        const valueJsonStart = value.indexOf('{');
        const valueJsonStr = value.substring(valueJsonStart);
        const parsed = JSON.parse(valueJsonStr);
        
        const compact = compactEvent(parsed);

        if (!compact || !compact.text) {
          console.log(`Deleting empty review: ${key}`);
          const deleteCmd = `wrangler kv key delete "${key}" --namespace-id 2d17bc191bfd41998759f2786e3dd6c3`;
          execSync(deleteCmd);
        }
      } catch (e) {
        console.warn(`Error processing key ${key}:`, e.message);
      }
    }

    console.log('Cleanup complete');
  } catch (e) {
    console.error('Cleanup failed:', e);
  }
}

function compactEvent(parsed) {
  try {
    const ev = parsed || {};
    const data = ev.data || {};
    const text = (data.text || data.message || '').trim();
    return {
      event: ev.event || null,
      text: text || null,
      date: data.date || data.created_at || null,
      id: data.id || null,
      rating: (typeof data.rating !== 'undefined') ? data.rating : (data.rate || null),
      author_name: data.author_name || data.user_name || data.client_name || data.author || null,
      author_surname: data.author_surname || data.user_surname || null,
      master_id: (typeof data.master_id !== 'undefined') ? data.master_id : (data.staff_id || null),
      master_name: data.master_name || data.master || data.staff_name || null
    };
  } catch (e) {
    return null;
  }
}

cleanEmptyReviews();