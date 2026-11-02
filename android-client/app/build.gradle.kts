plugins { id("com.android.application"); id("org.jetbrains.kotlin.android"); id("com.chaquo.python") }
android {
    namespace = "ua.ducksolar.b2.client"
    compileSdk = 35
    buildToolsVersion = "36.0.0"
    defaultConfig {
        applicationId = "ua.ducksolar.b2.client"
        minSdk = 26
        targetSdk = 35
        versionCode = 20000
        versionName = "b2.0.0"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    val signingPath = providers.environmentVariable("DS_ANDROID_KEYSTORE").orNull
    if (!signingPath.isNullOrBlank()) {
        signingConfigs.create("publicRelease") {
            storeFile = file(signingPath)
            storePassword = providers.environmentVariable("DS_ANDROID_STORE_PASSWORD").get()
            keyAlias = providers.environmentVariable("DS_ANDROID_KEY_ALIAS").get()
            keyPassword = providers.environmentVariable("DS_ANDROID_KEY_PASSWORD").get()
        }
        buildTypes.getByName("release").signingConfig = signingConfigs.getByName("publicRelease")
    }

}
chaquopy {
    defaultConfig {
        version = "3.11"
        buildPython(providers.environmentVariable("DS_BUILD_PYTHON").orElse("python3.11").get())
        pip { install("cryptography==42.0.8"); install("spake2==0.9"); install("tzdata==2026.2") }
    }
}
dependencies {
    implementation(project(":lan-support"))
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}

