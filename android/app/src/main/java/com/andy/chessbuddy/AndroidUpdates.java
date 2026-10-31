package com.andy.chessbuddy;

import java.io.ByteArrayOutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONObject;

/** Public release metadata only. Installation remains with Android's package installer. */
final class AndroidUpdates {
    static final String REPOSITORY = "https://github.com/andycheng2018/ai-chess-coach";
    private static final Pattern TAG = Pattern.compile("android-v([1-9][0-9]{0,8})");

    static JSONObject selectRelease(JSONArray releases, int currentCode) throws Exception {
        JSONObject selected = new JSONObject().put("available", false).put("currentCode", currentCode);
        long newest = currentCode;
        for (int index = 0; index < releases.length(); index++) {
            JSONObject release = releases.optJSONObject(index);
            if (release == null || release.optBoolean("draft") || release.optBoolean("prerelease")) continue;
            String tag = release.optString("tag_name");
            Matcher match = TAG.matcher(tag);
            if (!match.matches()) continue;
            long code = Long.parseLong(match.group(1));
            if (code <= newest) continue;
            JSONArray assets = release.optJSONArray("assets");
            if (assets == null) continue;
            String expected = REPOSITORY + "/releases/download/" + tag + "/ChessBuddy-Standalone-Android.apk";
            for (int assetIndex = 0; assetIndex < assets.length(); assetIndex++) {
                JSONObject asset = assets.optJSONObject(assetIndex);
                if (asset == null || !"ChessBuddy-Standalone-Android.apk".equals(asset.optString("name"))
                    || !expected.equals(asset.optString("browser_download_url")) || asset.optLong("size") <= 0) continue;
                selected = new JSONObject().put("available", true).put("currentCode", currentCode)
                    .put("versionCode", code).put("versionName", "1.0." + code)
                    .put("downloadUrl", expected).put("releaseUrl", REPOSITORY + "/releases/tag/" + tag);
                newest = code;
                break;
            }
        }
        return selected;
    }

    static JSONObject check() throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL("https://api.github.com/repos/andycheng2018/ai-chess-coach/releases?per_page=100").openConnection();
        connection.setConnectTimeout(10000); connection.setReadTimeout(15000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/vnd.github+json");
        connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28");
        connection.setRequestProperty("User-Agent", "ChessBuddy-Android/" + BuildConfig.VERSION_NAME);
        try {
            if (connection.getResponseCode() != 200) throw new Exception("The update service is unavailable. Try again later.");
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (var stream = connection.getInputStream()) {
                byte[] buffer = new byte[4096]; int size;
                while ((size = stream.read(buffer)) != -1) {
                    if (bytes.size() + size > 2_000_000) throw new Exception("The update response is too large.");
                    bytes.write(buffer, 0, size);
                }
            }
            return selectRelease(new JSONArray(new String(bytes.toByteArray(), StandardCharsets.UTF_8)), BuildConfig.VERSION_CODE)
                .put("currentVersion", BuildConfig.VERSION_NAME);
        } finally { connection.disconnect(); }
    }
}
