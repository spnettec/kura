package org.eclipse.kura.core.configuration;
import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.*;
import java.util.Arrays;
import java.util.jar.JarFile;
import java.util.jar.Manifest;
import org.junit.jupiter.api.Test;
class ConfigurationDeletionGuardPackagedLinkageTest {
    @Test void preparedMetadataAndCurrentPackageDeclareTheFrameworkDtoImport()throws Exception{
        Path classes=Path.of(ConfigurationServiceImpl.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        String entry="org/eclipse/kura/core/configuration/ConfigurationServiceImpl.class";
        byte[] current=Files.readAllBytes(classes.resolve(entry));
        assertTrue(new String(current,java.nio.charset.StandardCharsets.ISO_8859_1).contains("org/osgi/framework/dto/ServiceReferenceDTO"));
        // Unit tests precede packaging in a fresh reactor. Validate the actual
        // prepared packaging metadata even when no current JAR exists yet.
        try(var input=Files.newInputStream(classes.getParent().resolve("osgi/MANIFEST.MF"))){
            assertTrue(new Manifest(input).getMainAttributes().getValue("Import-Package").contains("org.osgi.framework.dto"));
        }
        Path artifact=classes.getParent().resolve("org.eclipse.kura.core.configuration-3.0.0-SNAPSHOT.jar");
        if(Files.isRegularFile(artifact))try(JarFile jar=new JarFile(artifact.toFile())){
            byte[] packaged;try(var input=jar.getInputStream(jar.getJarEntry(entry))){packaged=input.readAllBytes();}
            if(Arrays.equals(current,packaged))assertTrue(jar.getManifest().getMainAttributes().getValue("Import-Package").contains("org.osgi.framework.dto"));
        }
    }
}
