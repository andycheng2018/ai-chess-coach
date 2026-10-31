package com.andy.chessbuddy;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.jcraft.jsch.*;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Private app storage and strict, one-shot robot SSH. No automatic host trust. */
public final class StandaloneHost {
    private static Context context;
    private static final String KEY = "chessbuddy-config";
    public static void init(Context value) { context = value.getApplicationContext(); }

    private static SecretKey encryptionKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(KEY)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY, null);
    }

    public static synchronized String readSettings() throws Exception {
        String saved = context.getSharedPreferences(KEY, Context.MODE_PRIVATE).getString("encrypted", null);
        if (saved == null) return "{}";
        JSONObject envelope = new JSONObject(saved);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, encryptionKey(), new GCMParameterSpec(128, Base64.decode(envelope.getString("iv"), Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(envelope.getString("data"), Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }

    private static synchronized void writeSettings(JSONObject settings) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, encryptionKey());
        JSONObject envelope = new JSONObject();
        envelope.put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP));
        envelope.put("data", Base64.encodeToString(cipher.doFinal(settings.toString().getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP));
        if (!context.getSharedPreferences(KEY, Context.MODE_PRIVATE).edit().putString("encrypted", envelope.toString()).commit())
            throw new IOException("Could not save tablet settings.");
    }

    public static synchronized void configure(String supplied) throws Exception {
        JSONObject update = new JSONObject(supplied), current = new JSONObject(readSettings());
        String[] fields = {"openaiKey", "model", "botToken", "botUsername", "robotTarget", "robotFingerprint", "robotProfile", "elevenLabsKey", "voiceId"};
        for (String field : fields) if (update.has(field) && !update.optString(field).trim().isEmpty()) current.put(field, update.getString(field).trim());
        String target = current.optString("robotTarget").replaceFirst("^vbot@", "");
        if (!target.isEmpty() && !target.matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,252}")) throw new IllegalArgumentException("Enter the dog's hostname or IP, without options.");
        String fingerprint = current.optString("robotFingerprint");
        if (!fingerprint.isEmpty() && !fingerprint.matches("SHA256:[A-Za-z0-9+/]{43}")) throw new IllegalArgumentException("Enter the full SHA256 SSH host fingerprint.");
        if (!current.optString("robotProfile").isEmpty()) {
            JSONObject profile = new JSONObject(current.getString("robotProfile"));
            if (!profile.optString("hostKeyFingerprint").equals(fingerprint)) throw new IllegalArgumentException("Rehearsal profile and trusted fingerprint must match.");
        }
        writeSettings(current);
    }

    public static synchronized String publicSettings() throws Exception {
        JSONObject data = new JSONObject(readSettings()), result = new JSONObject();
        for (String field : new String[]{"model", "botUsername", "robotTarget", "robotFingerprint"}) result.put(field, data.optString(field));
        for (String field : new String[]{"openaiKey", "botToken", "robotProfile", "elevenLabsKey", "voiceId"}) result.put(field + "Configured", !data.optString(field).isEmpty());
        return result.toString();
    }

    public static synchronized String publicKey() throws Exception {
        JSONObject data = new JSONObject(readSettings());
        if (data.optString("sshPrivateKey").isEmpty()) {
            com.jcraft.jsch.KeyPair pair = com.jcraft.jsch.KeyPair.genKeyPair(new JSch(), com.jcraft.jsch.KeyPair.RSA, 3072);
            ByteArrayOutputStream privateBytes = new ByteArrayOutputStream(), publicBytes = new ByteArrayOutputStream();
            pair.writePrivateKey(privateBytes); pair.writePublicKey(publicBytes, "ChessBuddy-tablet");
            data.put("sshPrivateKey", privateBytes.toString("UTF-8")); data.put("sshPublicKey", publicBytes.toString("UTF-8").trim());
            pair.dispose(); writeSettings(data);
        }
        return data.getString("sshPublicKey");
    }

    private static Session session(String target, String password) throws Exception {
        JSONObject data = new JSONObject(readSettings());
        String host = target.replaceFirst("^vbot@", ""), configured = data.optString("robotTarget").replaceFirst("^vbot@", "");
        if (!host.equals(configured) || !host.matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,252}")) throw new IllegalArgumentException("This address is not the configured dog.");
        final String expected = data.optString("robotFingerprint");
        if (!expected.matches("SHA256:[A-Za-z0-9+/]{43}")) throw new IllegalArgumentException("Configure the verified robot fingerprint first.");
        JSch client = new JSch();
        client.setHostKeyRepository(new HostKeyRepository() {
            public int check(String suppliedHost, byte[] key) {
                try { String observed = "SHA256:" + Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(key), Base64.NO_WRAP | Base64.NO_PADDING);
                    return suppliedHost.equals(host) && MessageDigest.isEqual(observed.getBytes(StandardCharsets.US_ASCII), expected.getBytes(StandardCharsets.US_ASCII)) ? OK : CHANGED;
                } catch (Exception exception) { return CHANGED; }
            }
            public void add(HostKey key, UserInfo info) { throw new IllegalStateException("Automatic host-key acceptance is disabled."); }
            public void remove(String host, String type) {}
            public void remove(String host, String type, byte[] key) {}
            public String getKnownHostsRepositoryID() { return "Explicit tablet robot fingerprint"; }
            public HostKey[] getHostKey() { return new HostKey[0]; }
            public HostKey[] getHostKey(String host, String type) { return new HostKey[0]; }
        });
        if (password == null) {
            publicKey(); data = new JSONObject(readSettings());
            byte[] key = data.getString("sshPrivateKey").getBytes(StandardCharsets.UTF_8);
            try { client.addIdentity("tablet", key, null, null); } finally { Arrays.fill(key, (byte) 0); }
        }
        Session session = client.getSession("vbot", host, 22);
        session.setConfig("StrictHostKeyChecking", "yes");
        session.setConfig("PreferredAuthentications", password == null ? "publickey" : "password");
        if (password != null) session.setPassword(password);
        session.setServerAliveInterval(5000); session.setServerAliveCountMax(2);
        session.connect(8000); return session;
    }

    private static String execute(Session session, String command, int timeout) throws Exception {
        ChannelExec channel = (ChannelExec) session.openChannel("exec");
        ByteArrayOutputStream out = new ByteArrayOutputStream(), error = new ByteArrayOutputStream();
        channel.setCommand(command); channel.setInputStream(null); channel.setOutputStream(out); channel.setErrStream(error);
        try {
            channel.connect(5000); long end = System.nanoTime() + timeout * 1000000L;
            while (!channel.isClosed()) {
                if (out.size() > 1048576 || error.size() > 65536) throw new IOException("Robot response exceeded the bounded output limit; outcome unknown.");
                if (System.nanoTime() > end) throw new IOException("Robot request timed out; outcome unknown. Do not retry automatically.");
                Thread.sleep(25);
            }
            return new JSONObject().put("exitCode", channel.getExitStatus()).put("stdout", out.toString("UTF-8")).put("stderr", error.toString("UTF-8")).toString();
        } finally { channel.disconnect(); }
    }

    public static String runSsh(String target, String command, int timeout) throws Exception {
        Session session = session(target, null);
        try { return execute(session, command, Math.min(125000, Math.max(1000, timeout))); } finally { session.disconnect(); }
    }

    public static String installPublicKey(String password) throws Exception {
        String key = publicKey(); JSONObject data = new JSONObject(readSettings());
        String quoted = "'" + key.replace("'", "'\\''") + "'";
        String command = "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; grep -qxF " + quoted + " ~/.ssh/authorized_keys || printf '%s\\n' " + quoted + " >> ~/.ssh/authorized_keys";
        Session session = session(data.getString("robotTarget"), password);
        try { return execute(session, command, 10000); } finally { session.disconnect(); }
    }
}
