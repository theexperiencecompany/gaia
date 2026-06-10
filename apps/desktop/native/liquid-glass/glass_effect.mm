#include "../include/Common.h"
#include <napi.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <string>
#include <cctype>

#ifdef PLATFORM_OSX
#import <AppKit/AppKit.h>

// Simple registry so JS can still address a view by numeric id.
static std::map<int, NSView *> g_glassViews;
static int g_nextViewId = 0;

// Keys for objc-associated views on a container
static const void *kGlassEffectKey = &kGlassEffectKey;
static const void *kBackgroundViewKey = &kBackgroundViewKey;

// Utility: convert #RRGGBB or #RRGGBBAA to NSColor* (sRGB)
static NSColor* ColorFromHexNSString(NSString* hex)
{
  NSString* cleaned = [[hex stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]] uppercaseString];
  if ([cleaned hasPrefix:@"#"]) cleaned = [cleaned substringFromIndex:1];
  if (cleaned.length != 6 && cleaned.length != 8) return nil;

  unsigned int rgba = 0;
  NSScanner* scanner = [NSScanner scannerWithString:cleaned];
  if (![scanner scanHexInt:&rgba]) return nil;

  CGFloat r,g,b,a;
  if (cleaned.length == 6) {
    r = ((rgba & 0xFF0000) >> 16) / 255.0;
    g = ((rgba & 0x00FF00) >> 8)  / 255.0;
    b =  (rgba & 0x0000FF)        / 255.0;
    a = 1.0;
  } else {
    r = ((rgba & 0xFF000000) >> 24) / 255.0;
    g = ((rgba & 0x00FF0000) >> 16) / 255.0;
    b = ((rgba & 0x0000FF00) >> 8)  / 255.0;
    a =  (rgba & 0x000000FF)        / 255.0;
  }
  return [NSColor colorWithRed:r green:g blue:b alpha:a];
}

#define RUN_ON_MAIN(block)                                  \
  if ([NSThread isMainThread]) {                            \
    block();                                                \
  } else {                                                  \
    dispatch_sync(dispatch_get_main_queue(), block);        \
  }

/*!
 * AddGlassEffectView
 * -----------------
 * Creates an `NSGlassEffectView` (private) and inserts it behind the contentView
 * of the supplied Electron window. The handle received from JavaScript is the
 * pointer to the Cocoa `NSView` that backs the BrowserWindow. The view is
 * retained in a small registry so that we can manipulate or remove it later if
 * required. The function returns an integer identifier that can be used from
 * JavaScript.
 *
 * Returns –1 on error.
 */
extern "C" int AddGlassEffectView(unsigned char *buffer, bool opaque) {
  if (!buffer) {
    return -1;
  }

  __block int resultId = -1;

  RUN_ON_MAIN(^{
    NSView *rootView = *reinterpret_cast<NSView **>(buffer);
    if (!rootView) return;

    // GAIA patch: pin the window to its ACTIVE appearance. AppKit (and
    // the SwiftUI content inside NSGlassEffectView) derives the glass
    // material's active/subdued look from the window's key status —
    // non-key windows render a dimmed material with no public override.
    // Subclass the window at runtime so key-status queries always answer
    // YES, keeping the glass in its active appearance permanently.
    NSWindow *hostWindow = rootView.window;
    if (hostWindow) {
      Class base = object_getClass(hostWindow);
      const char *subName =
          [[NSString stringWithFormat:@"GAIAAlwaysActive_%s", class_getName(base)]
              UTF8String];
      Class sub = objc_getClass(subName);
      if (!sub) {
        sub = objc_allocateClassPair(base, subName, 0);
        if (sub) {
          IMP yes = imp_implementationWithBlock(^BOOL(id _self) { return YES; });
          class_addMethod(sub, @selector(isKeyWindow), yes, "c@:");
          class_addMethod(sub, NSSelectorFromString(@"hasKeyAppearance"), yes, "c@:");
          class_addMethod(sub, NSSelectorFromString(@"_hasActiveAppearance"), yes, "c@:");
          objc_registerClassPair(sub);
        }
      }
      if (sub) object_setClass(hostWindow, sub);
    }

    // Find the proper container - avoid NSThemeFrame
    NSView *container = rootView;

    // Remove previous glass and background views (if any)
    NSView *oldGlass = objc_getAssociatedObject(container, kGlassEffectKey);
    if (oldGlass) [oldGlass removeFromSuperview];
    
    NSView *oldBackground = objc_getAssociatedObject(container, kBackgroundViewKey);
    if (oldBackground) [oldBackground removeFromSuperview];

    NSRect bounds = container.bounds;

    NSBox *backgroundView = nil;
    

    NSView *glass = nil;
    Class glassCls = NSClassFromString(@"NSGlassEffectView");
    if (glassCls) {
      /**
      * GLASS VIEW
      */
      glass = [[glassCls alloc] initWithFrame:bounds];

      if (opaque) {
        // Create a background view behind the glass view using NSBox for proper background color
        backgroundView = [[NSBox alloc] initWithFrame:bounds];
        backgroundView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
        backgroundView.boxType = NSBoxCustom;
        backgroundView.borderType = NSNoBorder;
        backgroundView.fillColor = [NSColor windowBackgroundColor];
        backgroundView.wantsLayer = YES;
        
        
        // Add the background view first (bottom layer)
        [container addSubview:backgroundView positioned:NSWindowBelow relativeTo:nil];
      }
    } else {
      /**
      * FALLBACK VISUAL EFFECT VIEW
      */
      NSVisualEffectView *visual = [[NSVisualEffectView alloc] initWithFrame:bounds];
      visual.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
      visual.blendingMode = NSVisualEffectBlendingModeBehindWindow;
      visual.material = NSVisualEffectMaterialUnderWindowBackground;
      visual.state = NSVisualEffectStateActive;
      glass = visual;
    }

    // Ensure autoresize if we created a private glass view too
    glass.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;

    // Add the glass view (positioned relative to background view if opaque, or below everything if not)
    if (opaque && backgroundView) {
      [container addSubview:glass positioned:NSWindowAbove relativeTo:backgroundView];
    } else {
      [container addSubview:glass positioned:NSWindowBelow relativeTo:nil];
    }
    
    // Associate views with the container for cleanup
    objc_setAssociatedObject(container, kGlassEffectKey, glass, OBJC_ASSOCIATION_RETAIN);
    if (backgroundView) {
      objc_setAssociatedObject(container, kBackgroundViewKey, backgroundView, OBJC_ASSOCIATION_RETAIN);
    } else {
      objc_setAssociatedObject(container, kBackgroundViewKey, nil, OBJC_ASSOCIATION_ASSIGN);
    }

 

    int id = g_nextViewId++;
    g_glassViews[id] = glass;
    resultId = id;
  });

  return resultId;
}

// Configure glass view by id
extern "C" void ConfigureGlassView(int viewId, double cornerRadius, const char* tintHex) {
  RUN_ON_MAIN(^{
    auto it = g_glassViews.find(viewId);
    if (it == g_glassViews.end()) return;
    NSView* glass = it->second;

    // Corner radius via CALayer
    glass.wantsLayer = YES;
    glass.layer.cornerRadius = cornerRadius;
    glass.layer.masksToBounds = YES;

    // corner radius for the background view
    NSView* container = glass.superview;
    NSView* backgroundView = objc_getAssociatedObject(container, kBackgroundViewKey);
    if (backgroundView) {
      backgroundView.wantsLayer = YES;
      backgroundView.layer.cornerRadius = cornerRadius;
      backgroundView.layer.masksToBounds = YES;
    }

    if (tintHex && strlen(tintHex) > 0) {
      NSString* hex = [NSString stringWithUTF8String:tintHex];
      NSColor* c = ColorFromHexNSString(hex);
      if (c && [glass respondsToSelector:@selector(setTintColor:)]) {
        [(id)glass setTintColor:c];
      } else if (c) {
        glass.layer.backgroundColor = c.CGColor;
      }
    }
  });
}

// -----------------------------------------------------------------------------
// Dynamically set private properties on a previously created glass view
// -----------------------------------------------------------------------------

// Helper that converts a C-string key (e.g. "variant") into the Objective-C
// selector for its private setter (e.g. set_variant:). It automatically adds
// the leading underscore when missing.
static SEL SetterFromKey(const std::string &key, bool privateVariant) {
  std::string name;
  if (privateVariant) {
    // ensure leading underscore
    if (!key.empty() && key.front() != '_')
      name = "_" + key;
    else
      name = key;
    name = "set" + name;
  } else {
    // camel-case public variant: set + CapitalizedFirst + rest
    if (key.empty()) return nil;
    name = "set";
    name += toupper(key[0]);
    name += key.substr(1);
  }
  name += ":";
  return sel_registerName(name.c_str());
}

static SEL ResolveSetter(id obj, const char* cKey) {
  if (!cKey) return nil;
  std::string key(cKey);
  if (key.empty()) return nil;
  // Try private style first (set_<key>:)
  SEL sel = SetterFromKey(key, true);
  if ([obj respondsToSelector:sel]) return sel;
  // Then try public style (setKey:)
  sel = SetterFromKey(key, false);
  if ([obj respondsToSelector:sel]) return sel;
  return nil;
}

extern "C" void SetGlassViewIntProperty(int viewId, const char* key, long long value) {
#ifdef PLATFORM_OSX
  RUN_ON_MAIN(^{
    auto it = g_glassViews.find(viewId);
    if (it == g_glassViews.end()) return;
    NSView* glass = it->second;

    SEL sel = ResolveSetter(glass, key);
    if (!sel) return;
    if ([glass respondsToSelector:sel]) {
      ((void (*)(id, SEL, long long))objc_msgSend)(glass, sel, value);
    }
  });
#endif
}

extern "C" void SetGlassViewStringProperty(int viewId, const char* key, const char* value) {
#ifdef PLATFORM_OSX
  RUN_ON_MAIN(^{
    auto it = g_glassViews.find(viewId);
    if (it == g_glassViews.end()) return;
    NSView* glass = it->second;

    SEL sel = ResolveSetter(glass, key);
    if (!sel) return;
    if ([glass respondsToSelector:sel]) {
      NSString* val = value ? [NSString stringWithUTF8String:value] : @"";
      ((void (*)(id, SEL, id))objc_msgSend)(glass, sel, val);
    }
  });
#endif
}
#endif // PLATFORM_OSX 