export default {
  async fetch(request) {
    const url = new URL(request.url);
    const q = url.searchParams.get('q') || '';
    const count = url.searchParams.get('count') || '5';

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, OPTIONS' }
      });
    }

    if (!q) {
      return new Response(JSON.stringify({ error: 'missing q' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }

    const params = new URLSearchParams({ q, count });
    const braveUrl = 'https://api.search.brave.com/res/v1/web/search?' + params.toString();

    try {
      const resp = await fetch(braveUrl, {
        headers: { 'Accept': 'application/json', 'X-Subscription-Token': BRAVE_API_KEY }
      });
      const data = await resp.json();
      const slim = {
        results: (data.web?.results || []).map(r => ({
          title: r.title, url: r.url,
          description: (r.description || '').replace(/<[^>]+>/g, '')
        }))
      };
      return new Response(JSON.stringify(slim), {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'public, max-age=60' }
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }
  }
};
