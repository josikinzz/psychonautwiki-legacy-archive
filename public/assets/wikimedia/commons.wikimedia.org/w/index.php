/* CSS placed here is included on the file description page, also included on File-pages of Commons files on the local wikis */
/* Note that there are many non-Wikimedia / non-Wikipedia local wikis as well that use Commons as their repository! */
/* http://www.mediawiki.org/wiki/InstantCommons. Do not assume any language, direction, environment or Skin here. */

/* Hide TOC on file-pages */
.ns-6 #toc { display: none !important; }
 
/* Make {{location}} look like part of the info template */

.commons-file-information-table + table.commons-file-information-table,
.commons-file-information-table + div.commons-file-information-table > table
{
 border-top: 0;
 padding-top: 0;
 margin-top: -8px;
}



/* Used in several license and collection info templates in the File namespace */
/* such as [[Template:PermissionOTRS/layout]] */
.messagebox {
 border: 1px solid #aaa;
 background: #f9f9f9;
 width: 80%;
 margin: 0 auto 1em;
 padding: 0.2em;
 text-align: justify;
}

/* Styling the paramter fields */
.fileinfo-paramfield {
 background: #ccf;
 text-align: right;
 padding-right: 0.4em;
 width: 15%;
 font-weight: bold;
}