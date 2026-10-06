# Social Platform — Android & iOS apps

Native app shells (Capacitor 8) around the live Social Platform website.
The apps load the site set in `capacitor.config.json` → `server.url`, so every
change you deploy to the website shows up in the apps straight away — no app
store update needed unless you change the native side (icons, name, plugins).

```
mobile/
├── android/            Android Studio project (Gradle)
├── ios/                Xcode project (Swift Package Manager)
├── www/                splash page + offline page bundled inside the app
├── resources/          1024px logo + make_icons.py (regenerates all icons/splashes)
├── capacitor.config.json
└── package.json
```

The website side lives in `static/js/native.js` (loaded by `templates/index.html`).
It only runs inside the app and does four things:

* opens Google / Meta / X / TikTok / LinkedIn / Pinterest sign-in in the system
  browser tab (these providers block sign-in inside embedded web views);
* opens outside links in the system browser;
* Android back button closes the open dialog, then returns to the dashboard;
* refreshes the screen when the app comes back to the foreground.

**`native.js` must be deployed to the live site** before the apps are used,
otherwise connecting social accounts from inside the app won't work.

---

## One-time setup

```bash
cd mobile
npm install
```

Needs Node 20+. Android needs Android Studio (it includes the Java runtime and SDK).
iOS needs a Mac with Xcode 16+ and an Apple Developer account ($99/year).

After changing `capacitor.config.json`, `www/` or plugins, always run:

```bash
npx cap sync
```

---

## Android

### Test build (APK you can install directly)

Open in Android Studio: `npm run android`, then **Build → Build App Bundle(s) / APK(s) → Build APK(s)**.

Or from the command line (Windows PowerShell):

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
cd mobile\android
.\gradlew.bat assembleDebug
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`.
Copy it to a phone and open it (allow "Install unknown apps" once).

> On some corporate Windows machines Gradle fails with
> "Unable to establish loopback connection". Point the temp folder at a local drive first:
> ```powershell
> $env:TEMP = "D:\tmp\gradle"; $env:TMP = "D:\tmp\gradle"
> $env:JAVA_TOOL_OPTIONS = "-Djdk.net.unixdomain.tmpdir=D:/tmp/gradle -Djava.io.tmpdir=D:/tmp/gradle"
> ```

### Release build for Google Play

1. Create an upload key once (keep the file and passwords safe — never commit them):
   ```bash
   keytool -genkey -v -keystore socialplatform-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
   ```
2. In Android Studio: **Build → Generate Signed App Bundle / APK → Android App Bundle**,
   choose the key, build type `release`.
3. Output: `android/app/build/outputs/bundle/release/app-release.aab`.
4. Google Play Console → create app → upload the `.aab` to Internal testing first,
   fill in the store listing, privacy policy URL (`/privacy` on the site), data safety form.
5. For each new release raise `versionCode` and `versionName` in `android/app/build.gradle`.

---

## iOS (needs a Mac)

```bash
cd mobile
npm install
npx cap sync ios
npm run ios          # opens Xcode
```

In Xcode:

1. Select the **App** target → **Signing & Capabilities** → choose your Team.
   Change the Bundle Identifier if `com.socialplatform.app` is taken.
2. Pick a simulator or a connected iPhone and press **Run** to test.
3. For the App Store: **Product → Archive** → **Distribute App** → App Store Connect.
4. In App Store Connect, create the app, add screenshots and the privacy policy URL,
   then submit for review (TestFlight first is recommended).
5. For each new release raise **Version** and **Build** on the App target's General tab.

Camera / photo library / microphone permission texts are already in
`ios/App/App/Info.plist` (needed for picking media to upload).

---

## Push notifications in the app (Firebase)

Browsers get push notifications without any setup (Notifications page → Push
notifications → Turn on). The Android / iOS app uses Firebase Cloud Messaging,
which needs a free Firebase project — one time:

1. https://console.firebase.google.com → **Add project** (Google Analytics not needed).
2. **Add app → Android**, package name `com.socialplatform.app` → **Register app** →
   download **google-services.json** and put it in `mobile/android/app/`.
3. **Project settings → Service accounts → Generate new private key** (a .json file).
   Sign in to the website as SuperAdmin → **Notifications → Push notifications →
   Upload key** and choose that file. Keep it private — never commit it or send it by chat.
4. Add the plugin and rebuild the app:
   ```bash
   cd mobile
   npm install @capacitor/push-notifications
   npx cap sync
   ```
   then build and install the app again (see Android above).
5. In the app: **Notifications → Push notifications → Turn on** and allow notifications.

Add the plugin (step 4) only after `google-services.json` is in place — without it
Android can't start Firebase. For iOS also upload an APNs key in Firebase
(Project settings → Cloud Messaging) and turn on **Push Notifications** under
Signing & Capabilities in Xcode.

## Moving the site (e.g. to AWS)

Change `server.url` in `capacitor.config.json` to the new address, e.g.

```json
"server": { "url": "https://app.yourdomain.com", ... }
```

and the same address in `www/offline.html` (`var HOME = …`, used by its "Try again" button),
then `npx cap sync`, rebuild, and publish new versions of both apps.
Also add the new domain to each social platform's redirect URIs (see the AWS guide).

## Changing the icon / splash screen

Replace `resources/logo-1024.png` (square, 1024×1024 PNG), then:

```bash
python resources/make_icons.py
npx cap sync
```

## App name / ID

`appName` and `appId` in `capacitor.config.json`. Changing the ID after publishing
creates a different app in the stores — decide it before the first release.

---

## Known limits

* **Apple review:** Apple can reject apps that are "just a website" (guideline 4.2).
  The in-app sign-in handling, back-button and offline page help, but approval
  isn't guaranteed. Google Play is far less strict.
* **File downloads** (PDF/CSV reports) may not save from inside the app on every
  phone; use the website for exports if a download does nothing.
* **Internet required:** the app shows an offline page with a "Try again" button
  when the server can't be reached.
* On the free Render plan the first open after idle can take ~30 s while the server wakes up.
