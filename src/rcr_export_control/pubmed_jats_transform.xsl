<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output omit-xml-declaration="yes" indent="yes" method="xml" encoding="utf-8"/>
  <xsl:template match="/eSummaryResult/DocumentSummarySet">
      <ref-list>
        <title>References</title>
        <xsl:for-each select="DocumentSummary">
        <ref>
          <xsl:attribute name="id"><xsl:value-of select="concat('ref-', position())"/></xsl:attribute>
          <label><xsl:value-of select="position()" /></label>
          <element-citation>
            <xsl:attribute name="publication-type"><xsl:value-of select="PubType/flag[1]" /></xsl:attribute>
            
            <xsl:apply-templates />
          </element-citation>
        </ref>
        </xsl:for-each>
      </ref-list>
  </xsl:template>

  <xsl:template match="Authors">
  <person-group person-group-type="author"><xsl:apply-templates /></person-group>
  </xsl:template>

  <xsl:template match="Author">
  <name>
    <xsl:call-template name="tokenizeString">
      <xsl:with-param name="list" select="Name" />
      <xsl:with-param name="delimiter" select="' '" />
      <xsl:with-param name="firstTag" select="'surname'" />
      <xsl:with-param name="lastTag" select="'given-names'" />
      <xsl:with-param name="firstValue" select="''" />
    </xsl:call-template>
  </name>
  </xsl:template>

  <xsl:template match="PubDate">
    <xsl:call-template name="tokenizeString">
      <xsl:with-param name="list" select="." />
      <xsl:with-param name="delimiter" select="' '" />
      <xsl:with-param name="firstTag" select="'year'" />
      <xsl:with-param name="lastTag" select="'month'" />
      <xsl:with-param name="firstValue" select="''" />
    </xsl:call-template>
  </xsl:template>

  <xsl:template match="Source">
    <xsl:if test="text()[normalize-space()]">
      <source><xsl:value-of select="."/></source>
    </xsl:if>
  </xsl:template>

  <xsl:template match="Volume">
    <xsl:if test="text()[normalize-space()]">
      <volume><xsl:value-of select="."/></volume>
    </xsl:if>
  </xsl:template>

  <xsl:template match="Issue">
    <xsl:if test="text()[normalize-space()]">
      <issue><xsl:value-of select="."/></issue>
    </xsl:if>
  </xsl:template>

  <xsl:template match="ISSN">
    <xsl:if test="text()[normalize-space()]">
      <issn><xsl:value-of select="."/></issn>
    </xsl:if>
  </xsl:template>
  
  <xsl:template match="Title">
    <xsl:if test="text()[normalize-space()]">
      <article-title><xsl:value-of select="."/></article-title>
    </xsl:if>
  </xsl:template>
  
  <xsl:template match="Pages">
    <xsl:if test="text()[normalize-space()]">
      <page-range><xsl:value-of select="."/></page-range>
    </xsl:if>
  </xsl:template>

  <xsl:template name="tokenizeString">
      <!--passed template parameter -->
      <xsl:param name="list"/>
      <xsl:param name="delimiter"/>
      <xsl:param name="firstTag"/>
      <xsl:param name="lastTag"/>
      <xsl:param name="firstValue"/>
      <xsl:choose>
          <xsl:when test="contains($list, $delimiter)">
              <!-- get everything in front of the first delimiter -->
              <!-- <xsl:element name="{$firstTag}">
                  <xsl:value-of select="substring-before($list,$delimiter)"/>
              </xsl:element> -->
              <xsl:variable name="soFar">
                <xsl:value-of select="concat($firstValue, substring-before($list,$delimiter))"/></xsl:variable>
              <xsl:call-template name="tokenizeString">
                  <!-- store anything left in another variable -->
                  <xsl:with-param name="list" select="substring-after($list,$delimiter)"/>
                  <xsl:with-param name="delimiter" select="$delimiter"/>
                  <xsl:with-param name="firstTag" select="$firstTag"/>
                  <xsl:with-param name="lastTag" select="$lastTag"/>
                  <xsl:with-param name="firstValue" select="concat($soFar, ' ')"/>
              </xsl:call-template>
          </xsl:when>
          <xsl:otherwise>
              <xsl:choose>
                  <xsl:when test="$list = ''">
                      <xsl:text/>
                  </xsl:when>
                  <xsl:otherwise>
                    <xsl:if test="$firstValue != ''">
                      <xsl:element name="{$firstTag}">
                        <xsl:value-of select="$firstValue"/>
                      </xsl:element>
                      <xsl:element name="{$lastTag}">
                          <xsl:value-of select="$list"/>
                      </xsl:element>
                    </xsl:if>
                    <xsl:if test="$firstValue = ''">
                      <xsl:element name="{$firstTag}">
                        <xsl:value-of select="$list"/>
                      </xsl:element>
                    </xsl:if>
                  </xsl:otherwise>
              </xsl:choose>
          </xsl:otherwise>
      </xsl:choose>
  </xsl:template>

  <xsl:template match="text()|@*" />

</xsl:stylesheet>