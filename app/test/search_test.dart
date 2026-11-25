// Qidiruv mantig'i (agentdagi Python andozasi bilan bir xil natijalar). Bugun = 2026-11-24 (seshanba).
import 'package:flutter_test/flutter_test.dart';
import 'package:safevault_app/search.dart';
import 'package:safevault_app/session.dart';

RemoteFile rf(String id, String name, String cat, DateTime t) =>
    RemoteFile(id, 100, t.millisecondsSinceEpoch / 1000.0, {'name': name, 'category': cat});

void main() {
  final today = DateTime(2026, 11, 24, 15, 0);

  test("o'tgan oy / o'tgan hafta / kecha / oy nomi", () {
    var q = parseQuery("o'tgan oy saqlagan diplomimni topib ber", today);
    expect(q.keywords, ['diplomimni']);
    expect(q.start, DateTime(2026, 10, 1));
    expect(q.end, DateTime(2026, 10, 31));

    q = parseQuery("o'tgan hafta saqlagan hujjatlarim", today);
    expect(q.category, 'document');
    expect(q.keywords, isEmpty);
    expect(q.start, DateTime(2026, 11, 16));
    expect(q.end, DateTime(2026, 11, 22));

    q = parseQuery('kecha olingan rasmlar', today);
    expect(q.category, 'photo');
    expect(q.start, DateTime(2026, 11, 23));
    expect(q.end, DateTime(2026, 11, 23));

    q = parseQuery('oktabr 2026 videolar', today);
    expect(q.category, 'video');
    expect(q.start, DateTime(2026, 10, 1));
    expect(q.end, DateTime(2026, 10, 31));

    q = parseQuery('oxirgi rasm', today);
    expect(q.latest, isTrue);
    expect(q.category, 'photo');
  });

  test('qidiruv: nom, sana oralig\'i va sababini tushuntirish', () {
    final files = [
      rf('1', 'diplom.pdf', 'document', DateTime(2026, 10, 15, 12)),
      rf('2', 'IMG_1.jpg', 'photo', DateTime(2026, 11, 24, 9)),
    ];
    var r = searchFiles(files, parseQuery("o'tgan oy diplomimni topib ber", today));
    expect(r.files.map((f) => f.id), ['1']);
    expect(r.note, '');

    // o'tgan hafta hujjat yo'q: sanasiz natija va tushuntirish
    r = searchFiles(files, parseQuery("o'tgan hafta hujjatlarim", today));
    expect(r.files.map((f) => f.id), ['1']);
    expect(r.note, contains("hech narsa saqlanmagan"));

    // video yo'q: boshqa toifani ko'rsatmaydi
    r = searchFiles(files, parseQuery('videolarim', today));
    expect(r.files, isEmpty);
    expect(r.note, startsWith('Topilmadi'));
  });

  test('kontaktlar (.vcf) o\'qish va qidirish', () {
    const vcf = 'BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Alisher Karimov\r\nTEL;TYPE=CELL:+998 90 111-22-33\r\nEND:VCARD\r\n'
        'BEGIN:VCARD\r\nVERSION:3.0\r\nN:Rustamova;Dilnoza;;;\r\nTEL:+998935556677\r\nEND:VCARD\r\n'
        'BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Bobur\r\nEND:VCARD\r\n';
    final people = parseVcf(vcf);
    expect(people.map((c) => c.name), ['Alisher Karimov', 'Bobur', 'Dilnoza Rustamova']);
    expect(filterContacts(people, 'alisherning').map((c) => c.name), ['Alisher Karimov']);
    expect(filterContacts(people, '935556677').map((c) => c.name), ['Dilnoza Rustamova']);
    expect(filterContacts(people, "yo'q"), isEmpty);
  });
}
