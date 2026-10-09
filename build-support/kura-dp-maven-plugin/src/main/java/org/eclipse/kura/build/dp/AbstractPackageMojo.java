/* Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.build.dp;

import java.io.File;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.List;

import org.apache.maven.artifact.Artifact;
import org.apache.maven.plugin.AbstractMojo;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugins.annotations.Component;
import org.apache.maven.plugins.annotations.Parameter;
import org.apache.maven.project.MavenProject;
import org.apache.maven.project.MavenProjectHelper;

abstract class AbstractPackageMojo extends AbstractMojo {
    @Parameter(defaultValue = "${project}", readonly = true, required = true)
    protected MavenProject project;

    @Component
    private MavenProjectHelper projectHelper;

    @Parameter(property = "kura.build.qualifier")
    private String qualifier;

    @Parameter(property = "osgi-dp.skip", defaultValue = "false")
    private boolean skip;

    protected abstract List<Path> bundleFiles() throws MojoExecutionException;

    protected Path artifactFile(Artifact artifact) throws MojoExecutionException {
        File file = artifact == null ? null : artifact.getFile();
        if (file == null || !file.isFile()) {
            throw new MojoExecutionException("Missing packaged bundle " + artifact + "; run package/install first");
        }
        return file.toPath();
    }

    @Override
    public void execute() throws MojoExecutionException {
        if (skip) {
            return;
        }
        String version = project.getVersion();
        if (version.endsWith("-SNAPSHOT")) {
            String buildQualifier = qualifier;
            if (buildQualifier == null || buildQualifier.isBlank()) {
                buildQualifier = DateTimeFormatter.ofPattern("yyyyMMddHHmm").withZone(ZoneOffset.UTC)
                        .format(Instant.now());
            }
            version = version.substring(0, version.length() - "-SNAPSHOT".length()) + "." + buildQualifier;
        }
        Path output = Path.of(project.getBuild().getDirectory(),
                project.getArtifactId() + "_" + project.getVersion() + ".dp");
        try {
            DeploymentPackage.write(output, project.getArtifactId(), version, bundleFiles());
        } catch (IOException e) {
            throw new MojoExecutionException("Cannot build deployment package: " + e.getMessage(), e);
        }
        projectHelper.attachArtifact(project, "dp", output.toFile());
        getLog().info("Attached " + output + " (" + version + ")");
    }
}
