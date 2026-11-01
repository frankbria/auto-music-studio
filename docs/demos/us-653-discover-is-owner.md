# #653 Discovery marks the signed-in viewer's own clips

*2026-11-01T01:29:00Z by Showboat 0.6.1*
<!-- showboat-id: e8522be1-ce7c-4cd3-a576-c32b78da64b6 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_653` database). The seeded musician's clip is made public, and a second public clip from another account is inserted beside it. The same `/api/v1/discover/clips` listing is read anonymously and then with the musician's token.

```bash
. $DEMO/env.sh >/dev/null; M "db.clips.updateOne({_id: ObjectId('$CLIP_1')}, {\$set: {visibility: 'public', is_public: true, style_tags: ['lofi'], title: 'My Song'}}); var c = db.clips.findOne({_id: ObjectId('$CLIP_1')}); delete c._id; c.user_id = ObjectId(); c.title = 'Someone Else'; db.clips.insertOne(c).acknowledged"
```

```output
true
```

## 1. Anonymous: nobody's clip is marked as theirs

```bash
. $DEMO/env.sh >/dev/null; curl -s $DEMO_API/discover/clips | jq -c '[.clips[] | {title, is_owner}]'
```

```output
[{"title":"Someone Else","is_owner":false},{"title":"My Song","is_owner":false}]
```

## 2. Signed in: the musician's own clip is marked, the other is not

```bash
. $DEMO/env.sh >/dev/null; curl -s -H "Authorization: Bearer $TOKEN" $DEMO_API/discover/clips | jq -c '[.clips[] | {title, is_owner}]'
```

```output
[{"title":"Someone Else","is_owner":false},{"title":"My Song","is_owner":true}]
```

## 3. A bad token is a 401, not a silent anonymous read

```bash
. $DEMO/env.sh >/dev/null; curl -s -o /dev/null -w 'HTTP %{http_code}\n' -H 'Authorization: Bearer not-a-jwt' $DEMO_API/discover/clips
```

```output
HTTP 401
```

## 4. Web: the BFF forwards the token, and all three surfaces hide Report on the viewer's own clip

```bash
cd web && npx vitest run app/api/discover components/feed/FeedView.test.tsx components/search/SearchView.test.tsx components/explore/NewReleasesSection.test.tsx -t '653|Authorization|anonymous' --reporter=verbose 2>&1 | grep -E '✓|×|Tests ' | sed 's/ [0-9]*ms$//'
```

```output
 ✓ app/api/discover/clips/route.test.ts > GET /api/discover/clips > forwards the viewer's Authorization and the client IP (#653)
 ✓ app/api/discover/clips/route.test.ts > GET /api/discover/clips > sends no Authorization for an anonymous visitor
 ✓ app/api/discover/facets/route.test.ts > GET /api/discover/facets > proxies the facets without Authorization or the client query
 ✓ components/feed/FeedView.test.tsx > FeedView viewer ownership (#653) > sends the viewer's token and offers Report only on someone else's clip
 ✓ components/explore/NewReleasesSection.test.tsx > NewReleasesSection viewer ownership (#653) > sends the viewer's token and offers Report only on someone else's clip
 ✓ components/explore/NewReleasesSection.test.tsx > NewReleasesSection viewer ownership (#653) > stays anonymous for a signed-out visitor
 ✓ components/search/SearchView.test.tsx > SearchView viewer ownership (#653) > sends the viewer's token and offers Report only on someone else's clip
      Tests  7 passed | 25 skipped (32)
```
