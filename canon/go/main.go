// canon — the Bible as a hash table, as one static binary for the edge.
//
// Loads data/web.jsonl and data/xrefs.tsv (built by the Python side from the public-domain WEB), recomputes
// every verse key with the SAME normalisation and canonical JSON as canon/table.py, and refuses to start if
// a single key differs — so the Go and Python tables are provably the same commitment. Then serves the four
// tools a model calls, plus /verify for a quote, over HTTP. No CGO, no dependencies beyond x/text (NFKC).
//
//	canon -data ../data -addr 127.0.0.1:8040
//	canon -data ../data -check          # recompute keys and root, print, exit
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

type Verse struct {
	Book    string   `json:"book"`
	Abbr    string   `json:"abbr"`
	Chapter int      `json:"chapter"`
	Verse   int      `json:"verse"`
	Text    string   `json:"text"`
	Strongs []string `json:"strongs"`
	Key     string   `json:"key"`
	norm    string
}

type Xref struct {
	Book    string
	Chapter int
	Verse   int
	Votes   int
}

type Table struct {
	Translation string
	Rows        []*Verse
	byRef       map[string]*Verse
	byText      map[string]*Verse
	byWord      map[string][]int
	byStrong    map[string][]*Verse
	xrefs       map[string][]Xref
	Root        string
}

var spaces = regexp.MustCompile(`\s+`)

// normalise mirrors canon/table.py: NFKC, straight quotes, lower, punctuation → space, single spaces.
func normalise(s string) string {
	s = norm.NFKC.String(s)
	r := strings.NewReplacer("’", "'", "‘", "'", "“", `"`, "”", `"`, "—", " ", "–", " ")
	s = r.Replace(s)
	s = strings.ToLower(s)
	var b strings.Builder
	for _, c := range s {
		// Python's [^\w\s] with re.UNICODE: \w is letters, digits, underscore
		if unicode.IsLetter(c) || unicode.IsDigit(c) || c == '_' || unicode.IsSpace(c) {
			b.WriteRune(c)
		} else {
			b.WriteRune(' ')
		}
	}
	return strings.TrimSpace(spaces.ReplaceAllString(b.String(), " "))
}

// canonical JSON as validate.canonical_json_bytes: sorted keys, tight separators, no ASCII escaping.
func canonicalVerseKey(translation, book string, chapter, verse int, text string) string {
	// keys sorted: book, chapter, text, translation, verse
	js := fmt.Sprintf(`{"book":%s,"chapter":%d,"text":%s,"translation":%s,"verse":%d}`,
		jsonStr(book), chapter, jsonStr(normalise(text)), jsonStr(translation), verse)
	sum := sha256.Sum256([]byte(js))
	return hex.EncodeToString(sum[:])
}

func textKey(translation, text string) string {
	js := fmt.Sprintf(`{"text":%s,"translation":%s}`, jsonStr(normalise(text)), jsonStr(translation))
	sum := sha256.Sum256([]byte(js))
	return hex.EncodeToString(sum[:])
}

// jsonStr encodes like Python json.dumps(ensure_ascii=False): escapes only ", \, and control chars.
func jsonStr(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, c := range s {
		switch c {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		default:
			if c < 0x20 {
				fmt.Fprintf(&b, `\u%04x`, c)
			} else {
				b.WriteRune(c)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}

func refKey(book string, c, v int) string { return fmt.Sprintf("%s|%d|%d", book, c, v) }

func Load(dir string) (*Table, error) {
	t := &Table{Translation: "WEB", byRef: map[string]*Verse{}, byText: map[string]*Verse{}, byWord: map[string][]int{},
		byStrong: map[string][]*Verse{}, xrefs: map[string][]Xref{}}
	f, err := os.Open(filepath.Join(dir, "web.jsonl"))
	if err != nil {
		return nil, err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	h := sha256.New()
	mismatches := 0
	for sc.Scan() {
		if len(sc.Bytes()) == 0 {
			continue
		}
		var v Verse
		if err := json.Unmarshal(sc.Bytes(), &v); err != nil {
			return nil, err
		}
		k := canonicalVerseKey(t.Translation, v.Book, v.Chapter, v.Verse, v.Text)
		if k != v.Key {
			mismatches++
			if mismatches <= 3 {
				log.Printf("KEY MISMATCH %s %d:%d python=%s go=%s", v.Book, v.Chapter, v.Verse, v.Key[:12], k[:12])
			}
		}
		v.norm = normalise(v.Text)
		i := len(t.Rows)
		t.Rows = append(t.Rows, &v)
		t.byRef[refKey(v.Book, v.Chapter, v.Verse)] = &v
		t.byText[textKey(t.Translation, v.Text)] = &v
		for _, s := range v.Strongs {
			t.byStrong[s] = append(t.byStrong[s], &v)
		}
		seen := map[string]bool{}
		for _, w := range strings.Fields(v.norm) {
			if !seen[w] {
				seen[w] = true
				t.byWord[w] = append(t.byWord[w], i)
			}
		}
		kb, _ := hex.DecodeString(v.Key)
		h.Write(kb)
	}
	if mismatches > 0 {
		return nil, fmt.Errorf("%d verse keys differ between Go and Python — the two tables are not the same commitment", mismatches)
	}
	t.Root = hex.EncodeToString(h.Sum(nil))
	if xf, err := os.Open(filepath.Join(dir, "xrefs.tsv")); err == nil {
		defer xf.Close()
		xs := bufio.NewScanner(xf)
		for xs.Scan() {
			p := strings.Split(xs.Text(), "\t")
			if len(p) != 3 {
				continue
			}
			a, _ := parseOB(p[0])
			_, b := parseOB(p[1])
			votes, _ := strconv.Atoi(p[2])
			if a != "" && b.Book != "" {
				t.xrefs[a] = append(t.xrefs[a], Xref{b.Book, b.Chapter, b.Verse, votes})
			}
		}
		for k := range t.xrefs {
			sort.Slice(t.xrefs[k], func(i, j int) bool { return t.xrefs[k][i].Votes > t.xrefs[k][j].Votes })
		}
	}
	return t, nil
}

type ref struct {
	Book    string
	Chapter int
	Verse   int
}

func parseOB(s string) (string, ref) {
	p := strings.Split(s, ".")
	if len(p) != 3 {
		return "", ref{}
	}
	name, ok := abbrToName[p[0]]
	if !ok {
		return "", ref{}
	}
	c, e1 := strconv.Atoi(p[1])
	v, e2 := strconv.Atoi(p[2])
	if e1 != nil || e2 != nil {
		return "", ref{}
	}
	r := ref{name, c, v}
	return refKey(name, c, v), r
}

var refRe = regexp.MustCompile(`^((?:[1-3]\s?)?[A-Za-z]+(?:\s+of\s+[A-Za-z]+)?)\s+(\d+)\s+(\d+)(?:\s*-\s*(\d+))?$`)

// parseRef: "John 3:16", "John.3.16", "1 Cor 13:4", "John 3:14-18" → book, chapter, verse, end
func parseRef(s string) (string, int, int, int, bool) {
	s = strings.NewReplacer(".", " ", ":", " ").Replace(strings.TrimSpace(s))
	m := refRe.FindStringSubmatch(s)
	if m == nil {
		return "", 0, 0, 0, false
	}
	book := resolveBook(spaces.ReplaceAllString(m[1], " "))
	if book == "" {
		return "", 0, 0, 0, false
	}
	c, _ := strconv.Atoi(m[2])
	v, _ := strconv.Atoi(m[3])
	end := v
	if m[4] != "" {
		end, _ = strconv.Atoi(m[4])
	}
	return book, c, v, end, true
}

func resolveBook(raw string) string {
	key := strings.ToLower(strings.ReplaceAll(raw, " ", ""))
	for _, n := range bookNames {
		if strings.ToLower(strings.ReplaceAll(n, " ", "")) == key {
			return n
		}
	}
	for abbr, n := range abbrToName {
		if strings.ToLower(abbr) == key {
			return n
		}
	}
	if n, ok := aliases[strings.ToLower(raw)]; ok {
		return n
	}
	if len(key) >= 3 {
		for _, n := range bookNames {
			if strings.HasPrefix(strings.ToLower(strings.ReplaceAll(n, " ", "")), key) {
				return n
			}
		}
	}
	return ""
}

func (t *Table) Get(book string, c, v int) *Verse { return t.byRef[refKey(book, c, v)] }
func (t *Table) FindText(s string) *Verse        { return t.byText[textKey(t.Translation, s)] }

func (t *Table) rarest(words []string) string {
	best, n := "", int(^uint(0)>>1)
	for _, w := range words {
		if k := len(t.byWord[w]); k < n {
			best, n = w, k
		}
	}
	return best
}

func (t *Table) FindPhrase(s string) []*Verse {
	q := normalise(s)
	words := strings.Fields(q)
	if len(words) == 0 {
		return nil
	}
	var out []*Verse
	for _, i := range t.byWord[t.rarest(words)] {
		if strings.Contains(" "+t.Rows[i].norm+" ", " "+q+" ") {
			out = append(out, t.Rows[i])
		}
	}
	return out
}

// Nearest: token edit distance over candidates sharing the rarest words (or the window around `within`).
func (t *Table) Nearest(s string, within *ref, window int) (*Verse, int) {
	q := strings.Fields(normalise(s))
	if len(q) == 0 {
		return nil, 0
	}
	var cands []*Verse
	if within != nil {
		for d := -window; d <= window; d++ {
			if r := t.Get(within.Book, within.Chapter, within.Verse+d); r != nil {
				cands = append(cands, r)
			}
		}
	}
	if len(cands) == 0 {
		uniq := map[string]bool{}
		var ws []string
		for _, w := range q {
			if !uniq[w] {
				uniq[w] = true
				ws = append(ws, w)
			}
		}
		sort.Slice(ws, func(i, j int) bool { return len(t.byWord[ws[i]]) < len(t.byWord[ws[j]]) })
		if len(ws) > 8 {
			ws = ws[:8]
		}
		counts := map[int]int{}
		for _, w := range ws {
			for _, i := range t.byWord[w] {
				counts[i]++
			}
		}
		type kv struct{ i, n int }
		var sc []kv
		for i, n := range counts {
			sc = append(sc, kv{i, n})
		}
		sort.Slice(sc, func(a, b int) bool { return sc[a].n > sc[b].n || (sc[a].n == sc[b].n && sc[a].i < sc[b].i) })
		if len(sc) > 60 {
			sc = sc[:60]
		}
		for _, x := range sc {
			cands = append(cands, t.Rows[x.i])
		}
	}
	var best *Verse
	bd := int(^uint(0) >> 1)
	for _, r := range cands {
		if d := edit(q, strings.Fields(r.norm)); d < bd {
			best, bd = r, d
		}
	}
	return best, bd
}

func edit(a, b []string) int {
	prev := make([]int, len(b)+1)
	for j := range prev {
		prev[j] = j
	}
	for i := 1; i <= len(a); i++ {
		cur := make([]int, len(b)+1)
		cur[0] = i
		for j := 1; j <= len(b); j++ {
			c := prev[j-1]
			if a[i-1] != b[j-1] {
				c++
			}
			cur[j] = min(prev[j]+1, cur[j-1]+1, c)
		}
		prev = cur
	}
	return prev[len(b)]
}

func refStr(v *Verse) string { return fmt.Sprintf("%s %d:%d", v.Book, v.Chapter, v.Verse) }

// ── the four tools (same contracts as canon/synth.py run_tool) ────────────────────────────────────
func (t *Table) Tool(name string, args map[string]any) any {
	str := func(k string) string {
		if s, ok := args[k].(string); ok {
			return s
		}
		return ""
	}
	num := func(k string, d int) int {
		if f, ok := args[k].(float64); ok {
			return int(f)
		}
		return d
	}
	switch name {
	case "read_passage":
		book, c, v, end, ok := parseRef(str("ref"))
		if !ok {
			return map[string]any{"error": "could not parse ref"}
		}
		var out []map[string]any
		for i := v; i <= end; i++ {
			if r := t.Get(book, c, i); r != nil {
				out = append(out, map[string]any{"ref": refStr(r), "text": r.Text, "key": r.Key})
			}
		}
		if out == nil {
			return map[string]any{"error": str("ref") + " is not in the canon"}
		}
		return map[string]any{"verses": out}
	case "find_text":
		txt := str("text")
		if r := t.FindText(txt); r != nil {
			return map[string]any{"match": "exact", "ref": refStr(r), "text": r.Text, "key": r.Key}
		}
		if c := t.FindPhrase(txt); len(c) == 1 {
			return map[string]any{"match": "contains", "ref": refStr(c[0]), "text": c[0].Text, "key": c[0].Key}
		} else if len(c) > 1 {
			var cs []map[string]any
			for _, r := range c[:min(5, len(c))] {
				cs = append(cs, map[string]any{"ref": refStr(r), "text": r.Text})
			}
			return map[string]any{"match": "ambiguous", "candidates": cs}
		}
		if r, d := t.Nearest(txt, nil, 3); r != nil {
			return map[string]any{"match": "nearest", "ref": refStr(r), "text": r.Text, "key": r.Key, "distance": d}
		}
		return map[string]any{"match": "none"}
	case "cross_refs":
		book, c, v, _, ok := parseRef(str("ref"))
		if !ok {
			return map[string]any{"error": "could not parse ref"}
		}
		lim := num("limit", 5)
		var out []map[string]any
		for i, x := range t.xrefs[refKey(book, c, v)] {
			if i >= lim {
				break
			}
			out = append(out, map[string]any{"ref": fmt.Sprintf("%s %d:%d", x.Book, x.Chapter, x.Verse), "votes": x.Votes})
		}
		if out == nil {
			out = []map[string]any{}
		}
		return map[string]any{"refs": out}
	case "word_study":
		strong := strings.ToUpper(str("strong"))
		book := str("book")
		lim := num("limit", 6)
		var out []map[string]any
		for _, r := range t.byStrong[strong] {
			if book != "" && r.Book != book {
				continue
			}
			out = append(out, map[string]any{"ref": refStr(r), "text": r.Text})
			if len(out) >= lim {
				break
			}
		}
		if out == nil {
			out = []map[string]any{}
		}
		return map[string]any{"strong": strong, "verses": out}
	}
	return map[string]any{"error": "unknown tool " + name}
}

// Verify a quote the way canon/verifier.py does: exact hash, else the nearest verse as the counterexample.
func (t *Table) VerifyQuote(quote, refS string) map[string]any {
	var within *ref
	if refS != "" {
		if b, c, v, _, ok := parseRef(refS); ok {
			within = &ref{b, c, v}
		} else {
			return map[string]any{"status": "ERROR", "detail": "could not parse ref " + refS}
		}
	}
	if hit := t.FindText(quote); hit != nil {
		if within != nil && (hit.Book != within.Book || hit.Chapter != within.Chapter || hit.Verse != within.Verse) {
			return map[string]any{"status": "MISMATCH", "detail": fmt.Sprintf("quote is %s but attributed to %s %d:%d", refStr(hit), within.Book, within.Chapter, within.Verse),
				"counterexample": map[string]any{"what": "ref", "claimed": refS, "recomputed": refStr(hit)}}
		}
		return map[string]any{"status": "CONFIRMED", "detail": "verbatim " + refStr(hit) + " (WEB)", "verse": refStr(hit), "key": hit.Key, "stratum": "pure"}
	}
	near, d := t.Nearest(quote, within, 3)
	if near == nil {
		return map[string]any{"status": "MISMATCH", "detail": "quote matches no verse in the canon"}
	}
	return map[string]any{"status": "MISMATCH", "detail": fmt.Sprintf("quote is not verbatim; nearest is %s at %d word edits", refStr(near), d),
		"counterexample": map[string]any{"what": "quote", "claimed": quote, "recomputed": near.Text, "off_by": d, "nearest": refStr(near)}}
}

func main() {
	data := flag.String("data", "../data", "directory with web.jsonl and xrefs.tsv")
	addr := flag.String("addr", "127.0.0.1:8040", "listen address")
	check := flag.Bool("check", false, "recompute every key and the root, print, exit")
	flag.Parse()
	t, err := Load(*data)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Fprintf(os.Stderr, "canon (go): %d verses, root %s…, keys identical to the Python table\n", len(t.Rows), t.Root[:12])
	if *check {
		fmt.Println(t.Root)
		return
	}
	mux := http.NewServeMux()
	writeJSON := func(w http.ResponseWriter, code int, v any) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(code)
		json.NewEncoder(w).Encode(v)
	}
	mux.HandleFunc("GET /manifest", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"translation": t.Translation, "verses": len(t.Rows), "root": t.Root, "engine": "go"})
	})
	mux.HandleFunc("POST /tool/{name}", func(w http.ResponseWriter, r *http.Request) {
		var args map[string]any
		if err := json.NewDecoder(r.Body).Decode(&args); err != nil {
			writeJSON(w, 400, map[string]any{"error": "bad json"})
			return
		}
		writeJSON(w, 200, t.Tool(r.PathValue("name"), args))
	})
	mux.HandleFunc("POST /verify", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Quote string `json:"quote"`
			Ref   string `json:"ref"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeJSON(w, 400, map[string]any{"error": "bad json"})
			return
		}
		writeJSON(w, 200, t.VerifyQuote(body.Quote, body.Ref))
	})
	log.Printf("canon tools on http://%s/", *addr)
	log.Fatal(http.ListenAndServe(*addr, mux))
}
