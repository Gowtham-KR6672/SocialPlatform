#!/usr/bin/env bash
# ============================================================
#  Creates the Google Play upload key, once.
#  - The key goes to ~/SocialPlatform-keys/ (outside the project, never committed).
#  - android/keystore.properties tells the release build where it is and holds its
#    password, so ./gradlew bundleRelease signs the bundle. It is ignored by git.
#  Back up the key file AND the password: without them you can't publish updates
#  (Google can reset a lost upload key, but only after a support request).
#
#  Run:  bash make-upload-key.sh      (from mobile/android)
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

KEYDIR="$HOME/SocialPlatform-keys"
KEY="$KEYDIR/socialplatform-upload.jks"
ALIAS="upload"
JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"
KEYTOOL="$JAVA_HOME/bin/keytool"

if [ -f "$KEY" ]; then
  echo "An upload key already exists: $KEY"
  echo "Keep using it. To start over, move it away first."
  exit 1
fi
[ -x "$KEYTOOL" ] || { echo "keytool not found. Install Android Studio or set JAVA_HOME."; exit 1; }

read -rsp "Choose a password for the upload key (at least 8 characters): " SP_KEY_PW; echo
read -rsp "Type it again: " PW2; echo
[ "$SP_KEY_PW" = "$PW2" ] || { echo "The passwords don't match. Nothing was created."; exit 1; }
[ ${#SP_KEY_PW} -ge 8 ] || { echo "Use at least 8 characters. Nothing was created."; exit 1; }
read -rp "Your name or company name (stored inside the key): " OWNER
OWNER=${OWNER//,/ }   # commas would break the certificate name

mkdir -p "$KEYDIR"; chmod 700 "$KEYDIR"
export SP_KEY_PW
"$KEYTOOL" -genkeypair -keystore "$KEY" -alias "$ALIAS" -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass:env SP_KEY_PW -keypass:env SP_KEY_PW -dname "CN=$OWNER"
chmod 600 "$KEY"

umask 077
cat > keystore.properties <<EOF
storeFile=$KEY
storePassword=$SP_KEY_PW
keyAlias=$ALIAS
keyPassword=$SP_KEY_PW
EOF

echo
echo "Upload key created: $KEY"
echo "Release builds are now signed (android/keystore.properties)."
echo "Back up the key file and the password somewhere safe, e.g. a password manager."
