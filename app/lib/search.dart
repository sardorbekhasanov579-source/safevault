// Zaxiradagi fayllarni tabiiy tilda (o'zbekcha) qidirish. Agentdagi search.py ning Dart nusxasi (qoida asosida, internetsiz).
// Qidiruv fayl nomi, turi va saqlangan sanasi bo'yicha ishlaydi (fayl ichidagi matn bo'yicha emas).
import 'session.dart';

const _months = {
  'yanvar': 1, 'fevral': 2, 'mart': 3, 'aprel': 4, 'may': 5, 'iyun': 6, 'iyul': 7,
  'avgust': 8, 'sentabr': 9, 'oktabr': 10, 'noyabr': 11, 'dekabr': 12,
};
const _categoryWords = {
  'rasm': 'photo', 'surat': 'photo', 'foto': 'photo', 'video': 'video',
  'kontakt': 'contact', 'raqam': 'contact', 'nomer': 'contact',
  'hujjat': 'document', 'dokument': 'document', 'document': 'document',
};
const _stop = {
  'topib', 'top', 'ber', 'bering', 'berchi', 'menga', 'mening', 'meni', 'saqlagan', 'saqlangan',
  'saqlab', 'saqlaganimni', 'fayl', 'faylni', 'fayllar', 'yubor', 'yuboring', 'kerak', 'qidir',
  'qidirib', "ko'rsat", "ko'rsating", 'yuklab', 'olib', 'iltimos', 'edi', 'bor', 'va', 'bilan',
  'uchun', 'menda', 'men', 'bu', 'shu', 'oxirgi', 'eng', 'qani', 'qayerda', 'qaysi', 'hammasi',
  'barcha', "o'tgan", 'oldingi', 'yil', 'oy', 'hafta', 'kun', 'bugun', 'kecha',
};

class SearchQuery {
  final List<String> keywords;
  final String? category; // photo | video | contact | document
  final DateTime? start;  // shu kun ham kiradi
  final DateTime? end;    // shu kun ham kiradi
  final bool latest;
  SearchQuery(this.keywords, this.category, this.start, this.end, this.latest);

  bool get isEmpty => keywords.isEmpty && category == null && start == null && end == null;
}

class SearchOutcome {
  final List<RemoteFile> files;
  final String note; // bo'sh bo'lmasa, foydalanuvchiga ko'rsatiladigan tushuntirish
  SearchOutcome(this.files, this.note);
}

String normalizeText(String t) {
  var s = t.toLowerCase();
  for (final ch in ['ʻ', 'ʼ', '’', '‘', '`', '´']) {
    s = s.replaceAll(ch, "'");
  }
  return s;
}

String fmtDay(DateTime d) =>
    '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';

List<DateTime> _monthBounds(int y, int m) => [DateTime(y, m, 1), DateTime(y, m + 1, 0)];

SearchQuery parseQuery(String text, DateTime now) {
  final today = DateTime(now.year, now.month, now.day);
  var rest = ' ${normalizeText(text)} ';
  DateTime? start, end;

  bool take(String pattern) {
    final m = RegExp(pattern).firstMatch(rest);
    if (m == null) return false;
    rest = '${rest.substring(0, m.start)} ${rest.substring(m.end)}';
    return true;
  }

  if (take(r"(?<![a-z'])(o'tgan|oldingi|avvalgi) oy(?![a-z'])")) {
    final prevYear = today.month == 1 ? today.year - 1 : today.year;
    final prevMonth = today.month == 1 ? 12 : today.month - 1;
    final b = _monthBounds(prevYear, prevMonth);
    start = b[0];
    end = b[1];
  } else if (take(r"(?<![a-z'])bu oy(?![a-z'])")) {
    final b = _monthBounds(today.year, today.month);
    start = b[0];
    end = b[1];
  } else if (take(r"(?<![a-z'])(o'tgan|oldingi|avvalgi) hafta(?![a-z'])")) {
    final back = today.weekday - 1 + 7;
    start = DateTime(today.year, today.month, today.day - back);
    end = DateTime(start.year, start.month, start.day + 6);
  } else if (take(r"(?<![a-z'])bu hafta(?![a-z'])")) {
    start = DateTime(today.year, today.month, today.day - (today.weekday - 1));
    end = today;
  } else if (take(r"(?<![a-z'])bugun(?![a-z'])")) {
    start = end = today;
  } else if (take(r"(?<![a-z'])kecha(?![a-z'])")) {
    start = end = DateTime(today.year, today.month, today.day - 1);
  } else if (take(r"(?<![a-z'])(o'tgan|oldingi|avvalgi) yil(?![a-z'])")) {
    start = DateTime(today.year - 1, 1, 1);
    end = DateTime(today.year - 1, 12, 31);
  } else if (take(r"(?<![a-z'])bu yil(?![a-z'])")) {
    start = DateTime(today.year, 1, 1);
    end = today;
  } else {
    for (final e in _months.entries) {
      final m = RegExp("(?<![a-z'])(${e.key})[a-z']*(\\s+oy[a-z']*)?").firstMatch(rest);
      if (m == null) continue;
      final ym = RegExp(r'(?<!\d)(20\d\d)(?!\d)').firstMatch(rest);
      final year = ym != null ? int.parse(ym.group(1)!) : (e.value <= today.month ? today.year : today.year - 1);
      final b = _monthBounds(year, e.value);
      start = b[0];
      end = b[1];
      rest = '${rest.substring(0, m.start)} ${rest.substring(m.end)}';
      if (ym != null) rest = rest.replaceAll(ym.group(1)!, ' ');
      break;
    }
  }

  final latest = RegExp(r"(?<![a-z'])(oxirgi|eng so'nggi|so'nggi)(?![a-z'])").hasMatch(normalizeText(text));
  String? category;
  final keywords = <String>[];
  for (final m in RegExp(r"[a-z0-9']+").allMatches(rest)) {
    final tok = m.group(0)!.replaceAll(RegExp(r"^'+|'+$"), '');
    if (tok.length < 3 || _stop.contains(tok)) continue;
    String? cat;
    for (final e in _categoryWords.entries) {
      if (tok.startsWith(e.key)) {
        cat = e.value;
        break;
      }
    }
    if (cat != null) {
      category ??= cat;
      continue;
    }
    keywords.add(tok);
  }
  return SearchQuery(keywords, category, start, end, latest);
}

List<String> _words(String name) =>
    normalizeText(name).split(RegExp(r"[^a-z0-9']+")).where((w) => w.isNotEmpty).toList();

bool _matches(String tok, List<String> words, String whole) {
  if (tok.length >= 4 && whole.contains(tok)) return true;
  for (final w in words) {
    if (w.length >= 4 && (tok.startsWith(w) || (tok.length >= 4 && w.startsWith(tok)))) return true;
  }
  return false;
}

String describeQuery(SearchQuery q) {
  final parts = <String>[];
  const names = {'photo': 'rasm', 'video': 'video', 'document': 'hujjat', 'contact': 'kontakt'};
  if (q.category != null) parts.add(names[q.category] ?? q.category!);
  if (q.keywords.isNotEmpty) parts.add('«${q.keywords.join(' ')}»');
  if (q.start != null && q.end != null) {
    parts.add(q.start == q.end ? fmtDay(q.start!) : '${fmtDay(q.start!)} – ${fmtDay(q.end!)}');
  }
  return parts.isEmpty ? 'barcha fayllar' : parts.join(', ');
}

/// [all] ichidan so'rovga mosini topadi (eng yangisi birinchi). Hech narsa topilmasa, sababini [SearchOutcome.note] ga yozadi.
SearchOutcome searchFiles(List<RemoteFile> all, SearchQuery q) {
  List<RemoteFile> run(bool useCategory, bool useDates) {
    final scored = <MapEntry<int, RemoteFile>>[];
    for (final f in all) {
      if (useCategory && q.category != null && f.category != q.category) continue;
      final ts = DateTime.fromMillisecondsSinceEpoch((f.uploadedAt * 1000).round());
      if (useDates && q.start != null && ts.isBefore(q.start!)) continue;
      if (useDates && q.end != null && !ts.isBefore(DateTime(q.end!.year, q.end!.month, q.end!.day + 1))) continue;
      var score = 0;
      if (q.keywords.isNotEmpty) {
        final words = _words(f.name);
        final whole = normalizeText(f.name);
        for (final k in q.keywords) {
          if (_matches(normalizeText(k), words, whole)) score++;
        }
        if (score == 0) continue;
      }
      scored.add(MapEntry(score, f));
    }
    scored.sort((a, b) {
      final c = b.key.compareTo(a.key);
      return c != 0 ? c : b.value.uploadedAt.compareTo(a.value.uploadedAt);
    });
    final out = scored.map((e) => e.value).toList();
    return (q.latest && out.isNotEmpty) ? [out.first] : out;
  }

  var res = run(true, true);
  if (res.isNotEmpty) return SearchOutcome(res, '');
  if (q.category != null && q.keywords.isNotEmpty) {
    res = run(false, true);
    if (res.isNotEmpty) return SearchOutcome(res, "Toifa bo'yicha topilmadi, nomi bo'yicha ko'rsatilmoqda.");
  }
  if (q.start != null || q.end != null) {
    res = run(true, false);
    if (res.isNotEmpty) {
      return SearchOutcome(res, "(${describeQuery(q)}) bo'yicha shu sanalarda hech narsa saqlanmagan. Sanadan qat'i nazar topilganlar:");
    }
  }
  return SearchOutcome([], 'Topilmadi (${describeQuery(q)}).');
}

// ---------------- kontaktlar (.vcf) ----------------
class VcfContact {
  final String name;
  final List<String> tels;
  VcfContact(this.name, this.tels);
}

List<VcfContact> parseVcf(String text) {
  final unfolded = text.replaceAll(RegExp(r'\r?\n[ \t]'), '');
  final out = <VcfContact>[];
  String? name;
  List<String>? tels;
  for (final raw in unfolded.split(RegExp(r'\r?\n'))) {
    final line = raw.trim();
    final up = line.toUpperCase();
    if (up == 'BEGIN:VCARD') {
      name = '';
      tels = <String>[];
    } else if (up == 'END:VCARD') {
      if (name != null && tels != null && (name.isNotEmpty || tels.isNotEmpty)) out.add(VcfContact(name, tels));
      name = null;
      tels = null;
    } else if (name != null && tels != null && line.contains(':')) {
      final i = line.indexOf(':');
      final key = line.substring(0, i).split(';').first.toUpperCase();
      final val = line.substring(i + 1).trim();
      if (key == 'FN' && val.isNotEmpty) {
        name = val;
      } else if (key == 'N' && name.isEmpty) {
        final p = val.split(';');
        name = [if (p.length > 1) p[1], p[0]].where((s) => s.isNotEmpty).join(' ').trim();
      } else if (key == 'TEL' && val.isNotEmpty) {
        tels.add(val);
      }
    }
  }
  out.sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
  return out;
}

String _digits(String s) => s.replaceAll(RegExp(r'\D'), '');

List<VcfContact> filterContacts(List<VcfContact> all, String query) {
  final toks = query.toLowerCase().trim().split(RegExp(r'\s+')).where((t) => t.isNotEmpty).toList();
  if (toks.isEmpty) return all;
  return all.where((c) {
    final name = c.name.toLowerCase();
    final words = name.split(' ');
    final digs = c.tels.map(_digits).toList();
    return toks.every((t) {
      final td = _digits(t);
      return name.contains(t) ||
          words.any((w) => w.length >= 3 && t.startsWith(w)) ||
          (td.length >= 3 && digs.any((d) => d.contains(td)));
    });
  }).toList();
}
