#!/usr/bin/env python3
"""Keep the explicit Maven artifact copy list in sync with runtime.json."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def filename(coordinates):
    return coordinates.replace(':', '-') + '.jar'


def pom():
    spec = json.loads((ROOT / 'runtime.json').read_text())
    coordinates = {item['coordinates'] for item in spec['bundles']} | {spec['framework'], spec['launcher']}
    items = []
    for coordinate in sorted(coordinates):
        parts = coordinate.split(':')
        classifier = f'<classifier>{parts[3]}</classifier>' if len(parts) > 3 else ''
        items.append(f'                <artifactItem><groupId>{parts[0]}</groupId><artifactId>{parts[1]}</artifactId><version>{parts[2]}</version>{classifier}<destFileName>{filename(coordinate)}</destFileName></artifactItem>')
    return '''<?xml version="1.0" encoding="UTF-8"?>
<!-- Artifact list generated from runtime.json by tools/generate_pom.py. -->
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.eclipse.kura</groupId><artifactId>kura-build-parent</artifactId><version>6.0.0-SNAPSHOT</version>
    <relativePath>../build-support/kura-build-parent/pom.xml</relativePath>
  </parent>
  <artifactId>kura-dev-runtime</artifactId>
  <packaging>pom</packaging>
  <name>Kura standalone development runtime</name>
  <properties><kura.dev.profile>auto</kura.dev.profile></properties>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId><artifactId>maven-dependency-plugin</artifactId>
        <executions><execution>
          <id>collect-runtime</id><phase>prepare-package</phase><goals><goal>copy</goal></goals>
          <configuration>
            <outputDirectory>${project.build.directory}/bundle-cache</outputDirectory>
            <overWriteSnapshots>true</overWriteSnapshots>
            <overWriteReleases>true</overWriteReleases>
            <artifactItems>
''' + '\n'.join(items) + '''
            </artifactItems>
          </configuration>
        </execution></executions>
      </plugin>
      <plugin>
        <groupId>org.codehaus.mojo</groupId><artifactId>exec-maven-plugin</artifactId>
        <executions><execution>
          <id>guard-clean-runtime</id><phase>pre-clean</phase><goals><goal>exec</goal></goals>
          <configuration>
            <executable>python3</executable>
            <arguments><argument>${project.basedir}/tools/runtime.py</argument><argument>guard</argument></arguments>
          </configuration>
        </execution><execution>
          <id>assemble-runtime</id><phase>package</phase><goals><goal>exec</goal></goals>
          <configuration>
            <executable>python3</executable>
            <arguments><argument>${project.basedir}/tools/runtime.py</argument><argument>assemble</argument><argument>--profile</argument><argument>${kura.dev.profile}</argument></arguments>
          </configuration>
        </execution></executions>
      </plugin>
    </plugins>
  </build>
</project>
'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    text = pom()
    if args.check:
        if (ROOT / 'pom.xml').read_text() != text:
            raise SystemExit('runtime.json changed: run python3 kura-dev-runtime/tools/generate_pom.py')
    else:
        (ROOT / 'pom.xml').write_text(text)
