package com.andy.vbotstudio;

import android.os.Bundle;
import android.view.WindowManager;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override protected void onCreate(Bundle savedInstanceState) {
        registerPlugin(StudioPlugin.class);
        super.onCreate(savedInstanceState);
        // Stage and Stop must stay reachable during a demo.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }
}
