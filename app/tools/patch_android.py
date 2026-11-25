"""flutter create yaratgan Android loyihasiga SafeVault uchun kerakli sozlamalarni qo'shadi.
Ishlatish: python patch_android.py <loyiha_papkasi>"""
import pathlib, re, sys

proj = pathlib.Path(sys.argv[1])
manifest = proj / "android/app/src/main/AndroidManifest.xml"
s = manifest.read_text(encoding="utf-8")

perms = [
    '<uses-permission android:name="android.permission.INTERNET"/>',
    '<uses-permission android:name="android.permission.READ_MEDIA_IMAGES"/>',
    '<uses-permission android:name="android.permission.READ_MEDIA_VIDEO"/>',
    '<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" android:maxSdkVersion="32"/>',
    '<uses-permission android:name="android.permission.READ_CONTACTS"/>',
    '<uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE"/>',
    '<uses-permission android:name="android.permission.USE_BIOMETRIC"/>',
    '<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION"/>',
    '<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION"/>',
    '<uses-permission android:name="android.permission.ACCESS_BACKGROUND_LOCATION"/>',
]
add = "".join("    " + p + "\n" for p in perms if p.split('"')[1] not in s)
if add:
    s = s.replace("<application", add + "    <application", 1)
if "usesCleartextTraffic" not in s:  # v0.1: uy tarmog'idagi http server uchun. HTTPS ga o'tilgach o'chiriladi.
    s = s.replace("<application", '<application android:usesCleartextTraffic="true"', 1)
s = re.sub(r'android:label="[^"]*"', 'android:label="SafeVault"', s, count=1)
manifest.write_text(s, encoding="utf-8")

# local_auth: MainActivity FlutterFragmentActivity bo'lishi kerak
for f in list(proj.glob("android/app/src/main/kotlin/**/MainActivity.kt")) + list(proj.glob("android/app/src/main/java/**/MainActivity.java")):
    t = f.read_text(encoding="utf-8")
    t = t.replace("io.flutter.embedding.android.FlutterActivity", "io.flutter.embedding.android.FlutterFragmentActivity")
    t = re.sub(r"\bFlutterActivity\b", "FlutterFragmentActivity", t)
    f.write_text(t, encoding="utf-8")

# flutter_secure_storage / local_auth uchun minSdk 23
for name in ("android/app/build.gradle.kts", "android/app/build.gradle"):
    f = proj / name
    if f.exists():
        t = f.read_text(encoding="utf-8")
        t = t.replace("minSdk = flutter.minSdkVersion", "minSdk = 23").replace("minSdkVersion flutter.minSdkVersion", "minSdkVersion 23")
        f.write_text(t, encoding="utf-8")

# Plaginlar eski compileSdk bilan tuzilgan bo'lsa (masalan 34), yangi AndroidX talab qiladigan 37 ga ko'taramiz (permission_handler_android shuni talab qiladi).
MARK = "SAFEVAULT-COMPILESDK-37"
KTS = """// SAFEVAULT-COMPILESDK-37
subprojects {
    fun currentSdk(ext: Any): Int? {
        try {
            val v = ext.javaClass.getMethod("getCompileSdk").invoke(ext)
            if (v is Int) return v
        } catch (_: Exception) {}
        try {
            val s = ext.javaClass.getMethod("getCompileSdkVersion").invoke(ext) as? String
            return s?.substringAfter("android-")?.toIntOrNull()
        } catch (_: Exception) {}
        return null
    }
    fun forceSdk(p: Project) {
        val ext = p.extensions.findByName("android") ?: return
        val cur = currentSdk(ext)
        if (cur != null && cur >= 37) return
        for (m in ext.javaClass.methods) {
            if ((m.name == "setCompileSdk" || m.name == "setCompileSdkVersion") && m.parameterCount == 1) {
                val t = m.parameterTypes[0]
                if (t == Int::class.javaPrimitiveType || t == Int::class.javaObjectType) {
                    try { m.invoke(ext, 37); return } catch (_: Exception) {}
                }
            }
        }
    }
    if (state.executed) forceSdk(this) else afterEvaluate { forceSdk(this) }
}
"""
GROOVY = """// SAFEVAULT-COMPILESDK-37
subprojects {
    def forceSdk = { p ->
        def ext = p.extensions.findByName("android")
        if (ext == null) return
        try {
            def cur = ext.compileSdk
            if (cur == null || cur < 37) ext.compileSdk = 37
        } catch (ignored) {
            try { ext.compileSdkVersion 37 } catch (ignored2) {}
        }
    }
    if (project.state.executed) forceSdk(project) else project.afterEvaluate { forceSdk(project) }
}
"""
for name, block in (("android/build.gradle.kts", KTS), ("android/build.gradle", GROOVY)):
    f = proj / name
    if f.exists():
        t = f.read_text(encoding="utf-8")
        if MARK in t:
            continue
        head = t.lstrip()
        if head.startswith(("plugins", "buildscript", "import")):
            t = t + "\n" + block
        else:
            t = block + "\n" + t
        f.write_text(t, encoding="utf-8")
        print("compileSdk tuzatishi qo'shildi:", name)
print("Android sozlamalari qo'shildi")
