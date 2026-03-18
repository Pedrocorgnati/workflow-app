# Stack traces — keep source file names and line numbers for Crashlytics/Logcat
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# Annotations (required by Kotlin Serialization, Hilt, etc.)
-keepattributes *Annotation*

# Strip android.util.Log calls in release (safety net — code should use Timber)
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
    public static int w(...);
    public static int e(...);
    public static int wtf(...);
}

# Timber — keep so production tree can be added if needed
-keep class timber.log.Timber { *; }
-keep class timber.log.Timber$* { *; }

# App model classes (used with kotlinx.serialization)
-keep @kotlinx.serialization.Serializable class com.workflowapp.remote.model.** { *; }
-keep @kotlinx.serialization.Serializable class com.workflowapp.remote.connection.** { *; }

# Parcelable
-keep class * implements android.os.Parcelable {
    public static final android.os.Parcelable$Creator *;
}

# Enums
-keepclassmembers enum * {
    public static **[] values();
    public static ** valueOf(java.lang.String);
}

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-keep class okio.** { *; }

# Kotlin Serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class **$$serializer { *; }

# Kotlin Coroutines
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}
-keepclassmembers class kotlinx.coroutines.** { volatile <fields>; }

# AndroidX Lifecycle
-keep class androidx.lifecycle.** { *; }
-keepclassmembers class * implements androidx.lifecycle.LifecycleObserver {
    <init>(...);
}

# AndroidX Security Crypto (EncryptedSharedPreferences)
-keep class androidx.security.crypto.** { *; }
-keepclassmembers class androidx.security.crypto.** { *; }
-dontwarn com.google.crypto.tink.**
-keep class com.google.crypto.tink.** { *; }
