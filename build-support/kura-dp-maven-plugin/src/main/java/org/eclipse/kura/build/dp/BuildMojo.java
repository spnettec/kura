/* Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.build.dp;

import java.nio.file.Path;
import java.util.List;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugins.annotations.LifecyclePhase;
import org.apache.maven.plugins.annotations.Mojo;

/** Attach this project's packaged bundle as a deployment package. */
@Mojo(name = "build", defaultPhase = LifecyclePhase.PACKAGE, threadSafe = true)
public class BuildMojo extends AbstractPackageMojo {
    @Override
    protected List<Path> bundleFiles() throws MojoExecutionException {
        return List.of(artifactFile(project.getArtifact()));
    }
}
