/* Copyright (c) 2026 Contributors to the Eclipse Foundation.
 * SPDX-License-Identifier: EPL-2.0
 */
package org.eclipse.kura.build.dp;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import org.apache.maven.artifact.Artifact;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugins.annotations.LifecyclePhase;
import org.apache.maven.plugins.annotations.Mojo;
import org.apache.maven.plugins.annotations.ResolutionScope;

/** Package explicitly declared bundles; transitive/private dependencies stay inside their owners. */
@Mojo(name = "package", defaultPhase = LifecyclePhase.PACKAGE,
        requiresDependencyResolution = ResolutionScope.RUNTIME, threadSafe = true)
public class PackageMojo extends AbstractPackageMojo {
    @Override
    protected List<Path> bundleFiles() throws MojoExecutionException {
        List<Path> result = new ArrayList<>();
        for (Artifact artifact : project.getDependencyArtifacts()) {
            if (Artifact.SCOPE_COMPILE.equals(artifact.getScope()) || Artifact.SCOPE_RUNTIME.equals(artifact.getScope())) {
                result.add(artifactFile(artifact));
            }
        }
        return result;
    }
}
