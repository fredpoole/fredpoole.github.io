Bitmap.prototype._drawTextOdd = Bitmap.prototype._drawTextBody;
Bitmap.prototype._drawTextBody = function(text, tx, ty, maxWidth) {
   if(text === "\x99"){
       arguments[0] = "";
       $gameMessage._addingTitles = true;
   }
   if(text === "\x98"){
       arguments[0] = "";
       $gameMessage._addingTitles = false;
       $gameMessage._currentToolTip++;
   }
   if($gameMessage._addingTitles){
       var y = SceneManager._scene._windowLayer.children[0].y;
       var padding = SceneManager._scene._windowLayer.children[0]._padding;
       var tt = document.createElement("div");
       tt.className = "tooltip";
       tt.innerHTML = "&nbsp;";
       tt.style.position = "absolute";
       tt.style.left = Math.round(tx + padding) + "px";
       tt.style.top = Math.round(ty + y - padding / 2) + "px";
       tt.style.width = Math.round(this.measureTextWidth(text)) + "px";
       var height = parseInt((this.fontSize+"").replace(/\D+/g,"")) + 5;
       tt.style.height = height + "px";
       tt.style.zIndex = "999";
       //tt.style.backgroundColor = "red"; // to debug title position
       tt.setAttribute("title", $gameMessage._toolTips[$gameMessage._currentToolTip]);
       document.body.appendChild(tt);
   }
   this._drawTextOdd.apply(this, arguments);
};
Game_Message.prototype.clearOdd = Game_Message.prototype.clear;
Game_Message.prototype.clear = function() {
   this.clearOdd.call(this, arguments);
    this._toolTips = [];
    this._currentToolTip = 0;
    this._addingTitles = false;
    var tt = document.getElementsByClassName("tooltip");
    while(tt.length > 0)
       tt[0].parentNode.removeChild(tt[0]);
};
Game_Message.prototype.add = function(text) {
   var tt = this._toolTips;
   text = text.replace(/\\\[TITLE:([^\]]+?)TEXT:([^\]]+?)\]/g, function(m, title, text){
       tt.push(title);
       return "\x99" + text + "\x98";
   });
    this._texts.push(text);
};