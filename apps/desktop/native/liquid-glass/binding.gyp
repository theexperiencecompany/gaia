{
  "targets": [
    {
      "target_name": "liquidglass",
      "sources": ["liquidglass.cc", "glass_effect.mm"],
      "include_dirs": ["<!(node -p \"require('node-addon-api').include_dir\")"],
      "defines": ["NAPI_DISABLE_CPP_EXCEPTIONS"],
      "conditions": [
        [
          "OS=='mac'",
          {
            "xcode_settings": {
              "OTHER_CPLUSPLUSFLAGS": ["-std=c++17", "-fobjc-arc"],
              "OTHER_LDFLAGS": ["-framework", "AppKit", "-framework", "QuartzCore"],
              "MACOSX_DEPLOYMENT_TARGET": "11.0"
            }
          }
        ]
      ]
    }
  ]
}
