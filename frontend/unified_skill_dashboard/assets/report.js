/* Small safe Markdown display: no HTML, links, images or executable content. */
(function(root){
  const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const inline=s=>escape(s).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>');
  function render(text){
    const lines=String(text).split('\n'),out=[];
    for(let i=0;i<lines.length;i++){
      const line=lines[i].trim();if(!line)continue;
      if(line.startsWith('|')&&i+1<lines.length&&/^\|[\s:|\-]+\|$/.test(lines[i+1].trim())){
        const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|');
        const headers=cells(line);out.push('<div class="ai-table-wrap"><table><thead><tr>'+headers.map(c=>'<th>'+inline(c)+'</th>').join('')+'</tr></thead><tbody>');i++;
        while(i+1<lines.length&&lines[i+1].trim().startsWith('|'))out.push('<tr>'+cells(lines[++i]).map(c=>'<td>'+inline(c)+'</td>').join('')+'</tr>');
        out.push('</tbody></table></div>');continue;
      }
      const heading=line.match(/^(#{1,3})\s+(.+)$/);
      if(heading){const level=Math.min(4,heading[1].length+1);out.push('<h'+level+'>'+inline(heading[2])+'</h'+level+'>');}
      else if(line.startsWith('>'))out.push('<blockquote>'+inline(line.slice(1))+'</blockquote>');
      else out.push('<p>'+inline(line)+'</p>');
    }
    return out.join('');
  }
  root.WorkbenchReport={render};if(typeof module!=='undefined')module.exports=root.WorkbenchReport;
})(typeof window==='undefined'?globalThis:window);
