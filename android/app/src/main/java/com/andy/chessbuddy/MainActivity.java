package com.andy.chessbuddy;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override protected void onCreate(android.os.Bundle savedInstanceState) {
        registerPlugin(StandalonePlugin.class);
        super.onCreate(savedInstanceState);
    }
}
