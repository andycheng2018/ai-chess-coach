package com.andy.vbotstudio;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.jcraft.jsch.ChannelExec;
import com.jcraft.jsch.HostKey;
import com.jcraft.jsch.HostKeyRepository;
import com.jcraft.jsch.JSch;
import com.jcraft.jsch.JSchException;
import com.jcraft.jsch.Session;
import com.jcraft.jsch.UserInfo;
import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/**
 * Private app storage and strict SSH to the dog. Trust comes only from a fingerprint the operator
 * entered. A dog's address changes between networks, so the key is its identity, not the address.
 * There is no automatic host-key acceptance, and streams never reconnect or replay.
 */
public final class StudioHost {
    /** Marks a message that's safe and useful to show the operator. */
    static final String REFUSAL = "vbot-refusal: ";
    private static final String KEY = "vbot-studio-config";
    private static final String HOST = "[A-Za-z0-9][A-Za-z0-9_.-]{0,252}";
    private static final String FINGERPRINT = "SHA256:[A-Za-z0-9+/]{43}";
    private static Context context;

    private StudioHost() {}

    public static void init(Context value) { context = value.getApplicationContext(); }

    private static SecretKey encryptionKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(KEY)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY, null);
    }

    private static synchronized JSONObject read() throws Exception {
        String saved = context.getSharedPreferences(KEY, Context.MODE_PRIVATE).getString("encrypted", null);
        if (saved == null) return new JSONObject();
        JSONObject envelope = new JSONObject(saved);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, encryptionKey(), new GCMParameterSpec(128, Base64.decode(envelope.getString("iv"), Base64.NO_WRAP)));
        return new JSONObject(new String(cipher.doFinal(Base64.decode(envelope.getString("data"), Base64.NO_WRAP)), StandardCharsets.UTF_8));
    }

    private static synchronized void write(JSONObject settings) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, encryptionKey());
        JSONObject envelope = new JSONObject();
        envelope.put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP));
        envelope.put("data", Base64.encodeToString(cipher.doFinal(settings.toString().getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP));
        if (!context.getSharedPreferences(KEY, Context.MODE_PRIVATE).edit().putString("encrypted", envelope.toString()).commit())
            throw new IOException("Could not save the pairing.");
    }

    /** Empty until a pairing has fully succeeded. */
    public static String trustedFingerprint() throws Exception {
        return read().optString("robotFingerprint");
    }

    private static synchronized String publicKey() throws Exception {
        JSONObject data = read();
        if (data.optString("sshPrivateKey").isEmpty()) {
            com.jcraft.jsch.KeyPair pair = com.jcraft.jsch.KeyPair.genKeyPair(new JSch(), com.jcraft.jsch.KeyPair.RSA, 3072);
            ByteArrayOutputStream privateBytes = new ByteArrayOutputStream(), publicBytes = new ByteArrayOutputStream();
            pair.writePrivateKey(privateBytes);
            pair.writePublicKey(publicBytes, "VBOT-Studio");
            pair.dispose();
            data.put("sshPrivateKey", privateBytes.toString("UTF-8"));
            data.put("sshPublicKey", publicBytes.toString("UTF-8").trim());
            write(data);
        }
        return data.getString("sshPublicKey");
    }

    private static String observedFingerprint(byte[] key) throws Exception {
        return "SHA256:" + Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(key), Base64.NO_WRAP | Base64.NO_PADDING);
    }

    private static String keyType(byte[] key) {
        try {
            int size = ((key[0] & 255) << 24) | ((key[1] & 255) << 16) | ((key[2] & 255) << 8) | (key[3] & 255);
            return new String(key, 4, size, StandardCharsets.US_ASCII);
        } catch (RuntimeException unreadable) {
            return "unknown";
        }
    }

    private static Session session(String target, final String expected, String password) throws Exception {
        final String host = target.replaceFirst("^vbot@", "");
        if (!host.matches(HOST)) throw new IOException(REFUSAL + "Enter the dog's address, without spaces or options.");
        if (!expected.matches(FINGERPRINT)) throw new IOException(REFUSAL + "Enter the full SHA256 fingerprint of the dog's SSH key.");
        final String[] mismatch = new String[1];
        JSch client = new JSch();
        client.setHostKeyRepository(new HostKeyRepository() {
            @Override public int check(String suppliedHost, byte[] key) {
                try {
                    String observed = observedFingerprint(key);
                    if (MessageDigest.isEqual(observed.getBytes(StandardCharsets.US_ASCII), expected.getBytes(StandardCharsets.US_ASCII))) return OK;
                    mismatch[0] = keyType(key) + " " + observed;
                } catch (Exception unreadable) {
                    mismatch[0] = "an unreadable key";
                }
                return CHANGED;
            }
            @Override public void add(HostKey key, UserInfo info) { throw new IllegalStateException("Automatic host-key acceptance is disabled."); }
            @Override public void remove(String ignoredHost, String type) {}
            @Override public void remove(String ignoredHost, String type, byte[] key) {}
            @Override public String getKnownHostsRepositoryID() { return "Operator-entered dog fingerprint"; }
            @Override public HostKey[] getHostKey() { return new HostKey[0]; }
            @Override public HostKey[] getHostKey(String ignoredHost, String type) { return new HostKey[0]; }
        });
        if (password == null) {
            publicKey();
            byte[] key = read().getString("sshPrivateKey").getBytes(StandardCharsets.UTF_8);
            try { client.addIdentity("vbot-studio", key, null, null); } finally { Arrays.fill(key, (byte) 0); }
        }
        Session session = client.getSession("vbot", host, 22);
        session.setConfig("StrictHostKeyChecking", "yes");
        session.setConfig("PreferredAuthentications", password == null ? "publickey" : "password");
        if (password != null) session.setPassword(password);
        session.setServerAliveInterval(5000);
        session.setServerAliveCountMax(2);
        try {
            session.connect(8000);
        } catch (JSchException error) {
            session.disconnect();
            if (mismatch[0] != null) {
                throw new IOException(REFUSAL + "This dog presented " + mismatch[0] + ", not the paired fingerprint. Don't accept it blindly: compare it on a computer that already trusts this dog.");
            }
            if (String.valueOf(error.getMessage()).toLowerCase(java.util.Locale.ROOT).contains("auth")) {
                throw new IOException(REFUSAL + (password == null
                    ? "The dog didn't accept this app's key. Pair the app with this dog again."
                    : "The dog refused that password."));
            }
            throw new IOException(REFUSAL + "Couldn't reach the dog at that address. Check its power and that both are on the same Wi-Fi.");
        }
        return session;
    }

    /** One-time, operator-confirmed. Trust is saved only after the dog accepted this app's key. */
    public static void pair(String target, String fingerprint, String password) throws Exception {
        String key = publicKey();
        String quoted = "'" + key.replace("'", "'\\''") + "'";
        String command = "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; grep -qxF "
            + quoted + " ~/.ssh/authorized_keys || printf '%s\\n' " + quoted + " >> ~/.ssh/authorized_keys";
        Session session = session(target, fingerprint, password);
        ChannelExec channel = null;
        try {
            channel = (ChannelExec) session.openChannel("exec");
            channel.setCommand(command);
            channel.setInputStream(null);
            channel.connect(5000);
            long end = System.nanoTime() + 10000 * 1000000L;
            while (!channel.isClosed()) {
                if (System.nanoTime() > end) throw new IOException(REFUSAL + "The dog didn't confirm the pairing in time.");
                Thread.sleep(25);
            }
            if (channel.getExitStatus() != 0) throw new IOException(REFUSAL + "The dog didn't confirm the pairing.");
        } finally {
            if (channel != null) channel.disconnect();
            session.disconnect();
        }
        JSONObject data = read();
        data.put("robotFingerprint", fingerprint);
        write(data);
    }

    /** One explicitly opened, pinned session. It never reconnects or retries a cue. */
    public static final class SshStream {
        private final Session session;
        private final ChannelExec channel;
        private final InputStream input;
        private final OutputStream output;
        private final ByteArrayOutputStream partial = new ByteArrayOutputStream();
        private boolean closed;

        private SshStream(String target, String command) throws Exception {
            String expected = trustedFingerprint();
            if (expected.isEmpty()) throw new IOException(REFUSAL + "Pair this app with the dog first.");
            session = session(target, expected, null);
            ChannelExec opening = null;
            try {
                opening = (ChannelExec) session.openChannel("exec");
                opening.setCommand(command);
                input = opening.getInputStream();
                output = opening.getOutputStream();
                opening.setErrStream(new OutputStream() { @Override public void write(int ignored) {} });
                opening.connect(5000);
                channel = opening;
            } catch (Exception error) {
                if (opening != null) opening.disconnect();
                session.disconnect();
                throw error;
            }
        }

        public void writeLine(String line) throws Exception {
            if (closed || line.length() > 4096 || line.indexOf('\n') >= 0) throw new IOException("Invalid or closed cue stream");
            output.write((line + "\n").getBytes(StandardCharsets.UTF_8));
            output.flush();
        }

        public String readLine(int timeout) throws Exception {
            long deadline = System.nanoTime() + timeout * 1000000L;
            do {
                while (input.available() > 0) {
                    int value = input.read();
                    if (value < 0) throw new EOFException("Dog session closed");
                    if (value == '\n') {
                        String line = partial.toString("UTF-8");
                        partial.reset();
                        return line;
                    }
                    partial.write(value);
                    if (partial.size() > 65536) throw new IOException("Dog session frame too large");
                }
                if (closed || channel.isClosed() || !session.isConnected()) throw new EOFException("Dog session closed; no replay");
                Thread.sleep(10);
            } while (System.nanoTime() < deadline);
            return "";
        }

        /** EOF makes the helper on the dog hand back the screen and release its lock. */
        public void close() {
            if (!closed) {
                closed = true;
                try { output.close(); } catch (IOException ignored) {}
                channel.disconnect();
                session.disconnect();
            }
        }
    }

    public static SshStream openSshStream(String target, String command) throws Exception {
        return new SshStream(target, command);
    }
}
