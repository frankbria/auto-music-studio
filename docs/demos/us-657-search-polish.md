# #657 Search polish: the R&B tile and a stale Load more

*2026-11-01T03:14:27Z by Showboat 0.6.1*
<!-- showboat-id: cb245e58-aaf2-40f8-b3d3-491e2c2dff5f -->

## 1. The R&B tile's style now finds clips tagged "r&b"

Live against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_657` database). The seeded clip is made public with the style tag "smooth r&b groove". The tile used to search `rnb`; it now searches `r&b`.

```bash
. $DEMO/env.sh >/dev/null; M "db.clips.updateOne({_id: ObjectId('$CLIP_1')}, {\$set: {visibility: 'public', is_public: true, style_tags: ['smooth r&b groove'], title: 'Late Night'}}).modifiedCount" >/dev/null; echo "style=rnb -> $(curl -s "$DEMO_API/discover/clips?style=rnb" | jq -c '[.clips[].title]')"; echo "style=r&b -> $(curl -s "$DEMO_API/discover/clips?style=r%26b" | jq -c '[.clips[].title]')"
```

```output
style=rnb -> []
style=r&b -> ["Late Night"]
```

## 2. A Load more answer for a search switched away and back is dropped, and the tile link is encoded

```bash
cd web && npx vitest run components/search/SearchView.test.tsx components/explore/GenreChannels.test.tsx -t '657' --reporter=verbose 2>&1 | grep -E '✓|×|Tests ' | sed 's/ [0-9]*ms$//'
```

```output
 ✓ components/explore/GenreChannels.test.tsx > GenreChannels > encodes a slug with a symbol, so R&B searches the style r&b (#657)
 ✓ components/search/SearchView.test.tsx > SearchView polish (#657) > drops a Load more answer when its search was replaced and restored meanwhile
 ✓ components/search/SearchView.test.tsx > SearchView polish (#657) > links the R&B tile to the style generated tags use
      Tests  3 passed | 13 skipped (16)
```
